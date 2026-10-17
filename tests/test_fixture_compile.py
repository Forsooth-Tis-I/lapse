import pytest

from lapse.config import ROOT_DIR
from lapse.contracts import ServicePolicy
from lapse.policy import compile as compiler
from lapse.policy.loader import load_policy_file
from scripts.load_fixture import load_persona

pytestmark = pytest.mark.db


@pytest.fixture
def fixture_policy():
    return load_policy_file(ROOT_DIR / "fixtures/policy.yaml")


@pytest.fixture
def persona_graph(isolated_graph, fixture_policy):
    policies, carriers = fixture_policy
    load_persona(isolated_graph, policies, carriers)
    return isolated_graph


def test_github_reset_requires_both_email_and_authenticator(persona_graph):
    assert persona_graph.ro_query(
        "MATCH (m:Method {id: 'm:github:reset_email_then_totp'})-[:GRANTS]->(a:Account), "
        "(m)-[need:NEEDS]->(r:Root) "
        "RETURN a.id, m.needs_password, need.as, r.id ORDER BY r.id"
    ).result_set == [
        ["github", False, "totp_device", "device_phone"],
        ["github", False, "login_email", "email_primary"],
    ]


def test_enables_exactly_matches_single_need_non_password_methods(persona_graph):
    method_rows = persona_graph.ro_query(
        "MATCH (m:Method)-[:GRANTS]->(target) "
        "OPTIONAL MATCH (m)-[:NEEDS]->(need) "
        "RETURN m.id, m.needs_password, target.id, collect(need.id)"
    ).result_set
    expected = {
        (needs[0], target) for _, password, target, needs in method_rows if not password and len(needs) == 1
    }
    actual = persona_graph.ro_query("MATCH (a)-[:ENABLES]->(b) RETURN a.id, b.id").result_set
    assert set(map(tuple, actual)) == expected
    assert len(actual) == len(expected)
    assert ("phone_old", "google") in expected
    assert ("email_primary", "github") not in expected
    assert ("device_phone", "github") not in expected


def test_mailbox_requires_matching_host_account(persona_graph):
    assert persona_graph.ro_query(
        "MATCH (m:Method {id: 'm:mailbox:email_primary'})-[:GRANTS]->(e:Email), "
        "(m)-[:NEEDS]->(a:Account) "
        "RETURN m.kind, m.needs_password, e.id, a.id"
    ).result_set == [["mailbox", False, "email_primary", "google"]]
    assert persona_graph.ro_query(
        "MATCH (a:Account {id: 'google'})-[:ENABLES]->(e:Email) RETURN e.id"
    ).result_set == [["email_primary"]]


def test_college_account_has_password_only_login(persona_graph):
    assert persona_graph.ro_query(
        "MATCH (m:Method)-[:GRANTS]->(:Account {id: 'college_workspace'}) "
        "OPTIONAL MATCH (m)-[:NEEDS]->(n) RETURN m.kind, m.needs_password, count(n)"
    ).result_set == [["login", True, 0]]


def test_unmodelled_splitwise_has_no_methods(persona_graph):
    assert persona_graph.ro_query(
        "MATCH (a:Account {id: 'splitwise'}) "
        "OPTIONAL MATCH (m:Method)-[:GRANTS]->(a) RETURN a.modelled, count(m)"
    ).result_set == [[False, 0]]


def test_fixture_computes_reissue_date_and_confirms_uses(persona_graph):
    assert persona_graph.ro_query(
        "MATCH (p:Phone {id: 'phone_old'}) RETURN p.drop_at, p.reissue_after, p.label"
    ).result_set == [["2026-10-31", "2027-01-29", "••4321 (Vi)"]]
    assert persona_graph.ro_query(
        "MATCH ()-[u:USES]->() RETURN collect(DISTINCT u.confirmed)"
    ).result_set == [[[True]]]
    evidence = persona_graph.ro_query(
        "MATCH (e:Evidence)-[:SUPPORTS]->(:Account), (e)-[:MENTIONS]->(:Root) "
        "RETURN e.msg_id, e.subject, e.snippet"
    ).result_set
    assert evidence
    assert all(msg_id and subject and len(snippet) <= 300 for msg_id, subject, snippet in evidence)


def test_recompile_replaces_methods_and_enables_without_duplicates(persona_graph, fixture_policy):
    queries = [
        "MATCH (m:Method)-[:GRANTS]->(t) RETURN m.id, t.id ORDER BY m.id, t.id",
        "MATCH (m:Method)-[e:NEEDS]->(n) RETURN m.id, e.as, n.id ORDER BY m.id, e.as, n.id",
        "MATCH (a)-[:ENABLES]->(b) RETURN a.id, b.id ORDER BY a.id, b.id",
    ]
    before = [persona_graph.ro_query(query).result_set for query in queries]
    assert ["m:github:reset_email_then_totp", "github"] in before[0]
    persona_graph.query("CREATE (:Method {id: 'stale'})")
    persona_graph.query(
        "MATCH (a:Root {id: 'device_phone'}), (b:Account {id: 'splitwise'}) CREATE (a)-[:ENABLES]->(b)"
    )
    compiler.compile_user_graph(persona_graph, fixture_policy[0])
    assert [persona_graph.ro_query(query).result_set for query in queries] == before
    assert persona_graph.ro_query("MATCH (m:Method {id: 'stale'}) RETURN m.id").result_set == []


@pytest.mark.parametrize(
    "closed_label, closed_id, removed_method",
    [
        ("Email", "email_primary", "m:mailbox:email_primary"),
        ("Account", "google", "m:mailbox:email_primary"),
    ],
)
def test_closed_mailbox_or_host_disables_mailbox_method(
    persona_graph,
    fixture_policy,
    closed_label,
    closed_id,
    removed_method,
):
    persona_graph.query(f"MATCH (n:{closed_label} {{id: $id}}) SET n.status = 'closed'", {"id": closed_id})
    compiler.compile_user_graph(persona_graph, fixture_policy[0])
    assert persona_graph.ro_query(
        "MATCH (m:Method {kind: 'mailbox'}) RETURN m.id ORDER BY m.id"
    ).result_set == [["m:mailbox:email_college"]]
    assert (
        persona_graph.ro_query("MATCH (m:Method {id: $id}) RETURN m.id", {"id": removed_method}).result_set
        == []
    )
    if closed_label == "Account":
        assert (
            persona_graph.ro_query(
                "MATCH (m:Method)-[:GRANTS]->(:Account {id: 'google'}) RETURN m.id"
            ).result_set
            == []
        )


def test_compilation_expands_role_combinations_and_skips_missing_roles(isolated_graph):
    policy = ServicePolicy.model_validate(
        {
            "service": {"id": "service", "name": "Service"},
            "methods": [
                {
                    "id": "and",
                    "kind": "reset",
                    "label": "Both factors",
                    "needs_roles": ["login_email", "totp_device"],
                },
                {"id": "missing", "kind": "reset", "label": "Missing phone", "needs_roles": ["login_phone"]},
            ],
        }
    )
    isolated_graph.query(
        "CREATE (a:Account {id: 'account', service_id: 'service', status: 'active'}), "
        "(e1:Root {id: 'e1'}), (e2:Root {id: 'e2'}), (d1:Root {id: 'd1'}), (d2:Root {id: 'd2'}), "
        "(a)-[:USES {role: 'login_email'}]->(e1), (a)-[:USES {role: 'login_email'}]->(e2), "
        "(a)-[:USES {role: 'totp_device'}]->(d1), (a)-[:USES {role: 'totp_device'}]->(d2)"
    )
    compiler.compile_user_graph(isolated_graph, [policy])
    assert isolated_graph.ro_query(
        "MATCH (m:Method)-[:NEEDS {as: 'login_email'}]->(e), "
        "(m)-[:NEEDS {as: 'totp_device'}]->(d) RETURN m.id, e.id, d.id ORDER BY m.id"
    ).result_set == [
        ["m:account:and", "e1", "d1"],
        ["m:account:and:1", "e1", "d2"],
        ["m:account:and:2", "e2", "d1"],
        ["m:account:and:3", "e2", "d2"],
    ]
    assert isolated_graph.ro_query("MATCH (m:Method) RETURN count(m)").result_set == [[4]]


def test_policy_graph_writes_templates_changes_and_carriers(isolated_graph, fixture_policy, monkeypatch):
    monkeypatch.setattr(compiler, "policy_graph", lambda: isolated_graph)
    policies, carriers = fixture_policy
    compiler.write_policy_graph(policies, carriers)
    compiler.write_policy_graph(policies, carriers)
    assert isolated_graph.ro_query(
        "MATCH (:Service {id: 'github'})-[:HAS_METHOD]->(m:MethodTemplate) "
        "WHERE m.template_id = 'reset_email_then_totp' RETURN m.needs_roles, m.needs_password"
    ).result_set == [[["login_email", "totp_device"], False]]
    assert isolated_graph.ro_query(
        "MATCH (:Service {id: 'figma'})-[:HAS_CHANGE]->(c:ChangeProcedure) "
        "RETURN c.root_kind, c.tier, c.requires"
    ).result_set == [["email", 1, ["email_otp_new"]]]
    assert isolated_graph.ro_query(
        "MATCH (c:Carrier {id: 'vi_in'}) RETURN c.reissue_after_days"
    ).result_set == [[90]]
    assert isolated_graph.ro_query("MATCH (s:Service) RETURN count(s)").result_set == [[len(policies)]]


@pytest.fixture
def researched_persona(isolated_graph):
    policies, _ = load_policy_file(ROOT_DIR / "lapse/policy/services.yaml")
    _, carriers = load_policy_file(ROOT_DIR / "lapse/policy/carriers.yaml")
    load_persona(isolated_graph, policies, carriers)
    return isolated_graph


def test_researched_persona_compiles_every_account(researched_persona):
    from lapse.graph.db import run

    actual = {
        row["account_id"]: (row["modelled"], row["method_count"])
        for row in run(researched_persona, "fixture_method_counts").rows
    }
    assert actual == {
        "amazon_in": (True, 5),
        "canva": (True, 3),
        "college_workspace": (True, 1),
        "coursera": (True, 2),
        "dropbox": (True, 2),
        "figma": (True, 2),
        "github": (True, 2),
        "google": (True, 3),
        "linkedin": (True, 3),
        "microsoft": (True, 2),
        "notion": (True, 3),
        "paypal": (True, 2),
        "spotify": (True, 2),
        "splitwise": (False, 0),
        "swiggy": (True, 1),
        "x": (True, 3),
        "zomato": (True, 1),
    }


@pytest.mark.parametrize(
    "account_id,method_id,expected_needs",
    [
        ("github", "m:github:reset_email_then_totp", ["device_phone", "email_primary"]),
        ("dropbox", "m:dropbox:reset_email_then_sms", ["email_primary", "phone_old"]),
    ],
)
def test_researched_resets_retain_enrolled_factor(researched_persona, account_id, method_id, expected_needs):
    rows = researched_persona.ro_query(
        "MATCH (m:Method {kind: 'reset'})-[:GRANTS]->(:Account {id: $id}), "
        "(m)-[:NEEDS]->(r) RETURN m.id, r.id ORDER BY m.id, r.id",
        {"id": account_id},
    ).result_set
    assert rows == [[method_id, root] for root in expected_needs]
    assert researched_persona.ro_query(
        "MATCH (:Root {id: 'email_primary'})-[:ENABLES]->(:Account {id: $id}) RETURN count(*)",
        {"id": account_id},
    ).result_set == [[0]]


def test_college_mailbox_password_does_not_bypass_enrolled_sms(researched_persona):
    researched_persona.query(
        "MATCH (a:Account {id: 'college_workspace'}), (r:Root {id: 'phone_old'}) "
        "CREATE (a)-[:USES {role: 'sms_2fa'}]->(r)"
    )
    policies, _ = load_policy_file(ROOT_DIR / "lapse/policy/services.yaml")
    compiler.compile_user_graph(researched_persona, policies, account_ids=["college_workspace"])
    assert researched_persona.ro_query(
        "MATCH (m:Method)-[:GRANTS]->(:Account {id: 'college_workspace'}) "
        "OPTIONAL MATCH (m)-[:NEEDS]->(n) RETURN m.id, m.needs_password, collect(n.id)"
    ).result_set == [["m:college_workspace:login_password_sms", True, ["phone_old"]]]
