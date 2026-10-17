import pytest
from redis.exceptions import ResponseError

from lapse.graph import db


@pytest.fixture
def queries(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "QUERY_DIR", tmp_path)

    def register(name, cypher):
        (tmp_path / f"{name}.cypher").write_text(cypher)
        return name

    return register


@pytest.mark.db
def test_named_query_write_read_and_trace(isolated_graph, queries):
    queries("create", "CREATE (a:Account {id: $id}) RETURN a.id AS id")
    queries("lookup", "MATCH (a:Account {id: $id}) RETURN a.id AS id")
    records = []

    written = db.run(isolated_graph, "create", {"id": "github"}, write=True)
    outcome = db.run(
        isolated_graph,
        "lookup",
        {"id": "github"},
        timeout_ms=5000,
        trace=lambda *record: records.append(record),
    )

    assert written.rows == outcome.rows == [{"id": "github"}]
    assert outcome.row_count == 1
    assert outcome.query_name == "lookup"
    assert outcome.ms >= 0
    assert records == [("lookup", {"id": "github"}, outcome.ms, 1)]


@pytest.mark.db
def test_empty_graph_read_and_read_only_enforcement(isolated_graph, queries):
    queries("lookup", "MATCH (a:Account) RETURN a.id AS id")
    queries("create", "CREATE (a:Account {id: 'created'}) RETURN a.id AS id")

    assert db.run(isolated_graph, "lookup").rows == []
    db.run(isolated_graph, "create", write=True)
    with pytest.raises(ResponseError):
        db.run(isolated_graph, "create")
    assert db.run(isolated_graph, "lookup").rows == [{"id": "created"}]


@pytest.mark.db
def test_failed_query_is_traced_and_still_raises(isolated_graph, queries):
    queries("create", "CREATE (:Account {id: 'created'})")
    db.run(isolated_graph, "create", write=True)
    records = []
    with pytest.raises(ResponseError):
        db.run(isolated_graph, "create", trace=lambda *record: records.append(record))
    assert len(records) == 1
    name, params, ms, count = records[0]
    assert (name, params, count) == ("create", {}, 0)
    assert ms >= 0


@pytest.mark.db
def test_plain_nodes_edges_paths_and_nested_results(isolated_graph, queries):
    isolated_graph.query(
        "CREATE (:Root:Phone {id: 'phone_old', last4: '4321'})"
        "-[:ENABLES {source: 'policy'}]->(:Account {id: 'google'})"
    )
    queries(
        "shapes",
        "MATCH p=(r:Phone)-[e:ENABLES]->(a:Account) "
        "RETURN r AS root, e AS edge, p AS path, {items: [a, r]} AS nested",
    )

    outcome = db.run(isolated_graph, "shapes")
    root = {"_labels": ["Root", "Phone"], "id": "phone_old", "last4": "4321"}
    account = {"_labels": ["Account"], "id": "google"}
    edge = {"_type": "ENABLES", "source": "policy"}
    assert outcome.rows == [
        {
            "root": root,
            "edge": edge,
            "path": {"nodes": [root, account], "edges": [edge]},
            "nested": {"items": [account, root]},
        }
    ]


@pytest.mark.db
def test_schema_can_be_applied_twice(isolated_graph):
    db.ensure_schema(isolated_graph)
    db.ensure_schema(isolated_graph)
    isolated_graph.query("CREATE (:Account {id: 'indexed'})")
    assert isolated_graph.ro_query("MATCH (a:Account {id: 'indexed'}) RETURN a.id").result_set == [
        ["indexed"]
    ]


def test_unknown_query_is_rejected(queries):
    queries("known", "RETURN 1 AS result")
    with pytest.raises(KeyError, match="unknown"):
        db.run(None, "unknown")


@pytest.mark.parametrize(
    "cypher",
    [
        "CREATE (:Account {id: 'not-admin'})",
        "MATCH (n) DETACH DELETE n",
        "CREATE INDEX FOR (a:Account) ON (a.id); CREATE (:Account)",
    ],
)
def test_admin_rejects_application_queries(cypher):
    with pytest.raises(ValueError, match="index schema"):
        db.execute_admin(None, cypher)
