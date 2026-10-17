from uuid import uuid4

import pytest

from lapse.contracts import Reached, ScenarioRequest, ScenarioResult
from lapse.graph import scenarios, views
from lapse.graph.db import graph
from lapse.policy.loader import load_policy_file
from scripts.load_fixture import load_persona

pytestmark = pytest.mark.db


@pytest.fixture
def view_graph(monkeypatch):
    g = graph(f"lapse:test:wp1:views:{uuid4().hex}")
    policies, carriers = load_policy_file("fixtures/policy.yaml")
    load_persona(g, policies, carriers)
    monkeypatch.setattr(views, "user_graph", lambda uid: g)
    monkeypatch.setattr(scenarios, "user_graph", lambda uid: g)
    try:
        yield g
    finally:
        g.delete()


def test_graph_payload_dependencies_and_and_constraints(view_graph):
    traced = []
    result = views.graph_view("test", trace=lambda name, *_: traced.append(name))
    nodes = {node["id"]: node for node in result["nodes"]}
    assert len(nodes) == 22
    assert nodes["phone_old"]["root"]["kind"] == "phone"
    assert nodes["phone_old"]["status"] == "retiring"
    assert nodes["splitwise"]["unknown"] is True
    assert nodes["google"]["affected"] is False
    assert nodes["google"]["round"] is None
    assert all(edge["source"] in nodes and edge["target"] in nodes for edge in result["edges"])
    assert len({edge["id"] for edge in result["edges"]}) == len(result["edges"])
    assert any(edge["source"] == "google" and edge["target"] == "email_primary" for edge in result["edges"])
    for account in ("dropbox", "github"):
        assert any(edge["target"] == account and "AND" in edge["label"] for edge in result["edges"])
    assert {"view_roots", "view_accounts", "view_uses", "view_methods"} <= set(traced)


def test_scenario_overlay_is_scoped_and_records_rounds(view_graph):
    scenario = ScenarioResult(
        id="scenario-one",
        kind="takeover",
        actor="stranger",
        root_ids=["phone_old"],
        rounds=1,
        affected_accounts=[Reached(node_id="google", label="Google", node_type="Account", round=1)],
        direct_accounts=["google"],
        unknown_accounts=["splitwise"],
        total_accounts=17,
        ms=1,
    )
    view_graph.query(
        "MATCH (a:Account {id: 'google'}), (p:Root {id: 'phone_old'}) "
        "CREATE (s:Scenario {id: $id, result_json: $result}) "
        "CREATE (s)-[:REACHED {round: 1}]->(a) "
        "CREATE (s)-[:REACHED {round: 0}]->(p) "
        "CREATE (a)-[:DERIVED {scenario: $id, method: 'm:google:reset_phone', round: 1}]->(p) "
        "CREATE (a)-[:DERIVED {scenario: 'another', method: 'other', round: 99}]->(p)",
        {"id": scenario.id, "result": scenario.model_dump_json()},
    )
    result = views.graph_view("test", scenario.id)
    nodes = {node["id"]: node for node in result["nodes"]}
    assert nodes["google"]["affected"] is True
    assert nodes["google"]["round"] == 1
    assert nodes["phone_old"]["round"] == 0
    overlay = [edge for edge in result["edges"] if edge["derived"]]
    assert len(overlay) == 1
    assert (overlay[0]["source"], overlay[0]["target"]) == ("phone_old", "google")
    assert overlay[0]["round"] == 1
    assert not any(edge["derived"] for edge in views.graph_view("test")["edges"])


def test_roots_account_detail_and_evidence_search(view_graph):
    assert {root.id for root in views.list_roots("test")} == {
        "phone_old",
        "phone_new",
        "email_primary",
        "email_college",
        "device_phone",
    }
    detail = views.account_detail("test", "github")
    assert detail["account"]["display"] == "GitHub"
    assert {use["root_id"] for use in detail["uses"]} == {"email_primary", "device_phone"}
    assert any(
        {need["id"] for need in method["needs"]} == {"email_primary", "device_phone"}
        for method in detail["methods"]
    )
    assert [item["id"] for item in detail["evidence"]] == ["evidence_3"]
    assert views.account_detail("test", "absent") == {
        "account": None,
        "uses": [],
        "methods": [],
        "evidence": [],
    }
    assert [item.id for item in views.search_evidence("test", "authenticator")] == ["evidence_3"]
    assert len(views.search_evidence("test", "demo", limit=1)) == 1
    assert views.search_evidence("test", "unfindableword") == []
    assert views.search_evidence("test", " ") == []
    assert views.search_evidence("test", "demo", limit=0) == []


def test_stats_counts_real_nodes_and_edges(view_graph):
    traced = []
    actual = views.stats("test", trace=lambda *args: traced.append(args))
    assert actual["nodes"] == view_graph.ro_query("MATCH (n) RETURN count(n)").result_set[0][0]
    assert actual["edges"] == view_graph.ro_query("MATCH ()-[e]->() RETURN count(e)").result_set[0][0]
    assert actual["by_label"]["Account"] == 17
    assert actual["by_label"]["Root"] == 5
    assert actual["by_label"]["Phone"] == 2
    assert actual["last_query_ms"] >= 0
    assert actual["last_query_ms"] == traced[-1][2]


@pytest.mark.parametrize(
    ("kind", "roots", "affected"),
    [
        (
            "takeover",
            ["phone_old"],
            {
                "google",
                "x",
                "amazon_in",
                "swiggy",
                "zomato",
                "notion",
                "spotify",
                "paypal",
                "dropbox",
                "linkedin",
            },
        ),
        ("lockout", ["email_college"], {"figma", "canva", "coursera", "microsoft"}),
    ],
)
def test_live_scenario_views_mark_affected_accounts(view_graph, kind, roots, affected):
    result = scenarios.run_scenario("test", ScenarioRequest(kind=kind, root_ids=roots))
    payload = views.graph_view("test", result.id)
    assert {node["id"] for node in payload["nodes"] if node["affected"]} == affected
    assert all(node["round"] is not None for node in payload["nodes"] if node["affected"])
    derived = [edge for edge in payload["edges"] if edge["derived"]]
    assert derived
    assert all(result.id in edge["id"] for edge in derived)


def test_lockout_survivor_derivation_matches_actual_reached_state(view_graph):
    result = scenarios.run_scenario("test", ScenarioRequest(kind="lockout", root_ids=["phone_old"]))
    payload = views.graph_view("test", result.id)
    google = next(node for node in payload["nodes"] if node["id"] == "google")
    assert google["affected"] is False
    assert google["round"] == 3
    edges = [edge for edge in payload["edges"] if edge["target"] == "google" and edge["derived"]]
    assert [(edge["source"], edge["method_id"], edge["round"]) for edge in edges] == [
        ("email_college", "m:google:reset_recovery_email", 3),
    ]
    lost = scenarios.explain("test", result.id, "dropbox")
    assert lost.outcome == "path"
    assert [(step.from_id, step.to_id) for step in lost.steps] == [("phone_old", "dropbox")]
