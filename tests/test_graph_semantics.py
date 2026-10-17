from uuid import uuid4

import pytest
from redis.exceptions import ResponseError

from lapse.contracts import ScenarioRequest
from lapse.graph import db, scenarios
from lapse.graph.closure import closure
from lapse.policy.loader import load_policy_file
from scripts.load_fixture import load_persona

pytestmark = pytest.mark.db


@pytest.fixture
def g(monkeypatch):
    graph = db.graph(f"lapse:test:wp1:{uuid4().hex}")
    monkeypatch.setattr(scenarios, "user_graph", lambda uid: graph)
    try:
        yield graph
    finally:
        try:
            graph.delete()
        except ResponseError as exc:
            if "Invalid graph operation on empty key" not in str(exc):
                raise


@pytest.fixture
def persona(g):
    policies, carriers = load_policy_file("fixtures/policy.yaml")
    load_persona(g, policies, carriers)
    return g


def setup(g, roots, accounts, methods):
    for kind in {root.get("kind", "phone") for root in roots}:
        db.run(
            g,
            f"fixture_roots_{kind}",
            {
                "roots": [
                    {"kind": kind, "status": "active", "label": root["id"], **root}
                    for root in roots
                    if root.get("kind", "phone") == kind
                ]
            },
            write=True,
        )
    db.run(g, "policy_service", {"services": [{"id": "test", "name": "Test"}]}, write=True)
    db.run(
        g,
        "fixture_accounts",
        {
            "accounts": [
                {
                    "id": account,
                    "display": account,
                    "service_id": "test",
                    "modelled": True,
                    "status": "active",
                }
                for account in accounts
            ]
        },
        write=True,
    )
    db.run(
        g,
        "compile_methods",
        {
            "methods": [
                {
                    "target_id": target,
                    "props": {
                        "id": method,
                        "label": method,
                        "needs_password": password,
                        "kind": "mailbox" if target.startswith("email") else "reset",
                    },
                }
                for method, target, _, password in methods
            ]
        },
        write=True,
    )
    db.run(
        g,
        "compile_needs",
        {
            "needs": [
                {"method_id": method, "node_id": need, "role": "test"}
                for method, _, needs, _ in methods
                for need in needs
            ]
        },
        write=True,
    )


def ids(result):
    return {item.node_id for item in result.affected_accounts}


def test_simple_or(g):
    setup(g, [{"id": "a"}, {"id": "b"}], ["x"], [("one", "x", ["a"], False), ("two", "x", ["b"], False)])
    result = closure(g, ["a"])
    assert set(result.reached) == {"a", "x"}
    assert result.reached["x"].round == 1
    assert result.needs["x"] == ["a"]


def test_and_gate_blocks_stranger(g):
    setup(g, [{"id": "a"}, {"id": "b"}], ["x"], [("both", "x", ["a", "b"], False)])
    assert set(closure(g, ["a"]).reached) == {"a"}
    assert set(closure(g, ["a", "b"]).reached) == {"a", "b", "x"}
    assert scenarios.direct_dependents("test", "a") == []


def test_unseeded_cycle(g):
    setup(g, [{"id": "root"}], ["x", "y"], [("forward", "x", ["y"], False), ("back", "y", ["x"], False)])
    assert set(closure(g, ["root"]).reached) == {"root"}
    assert set(closure(g, ["x"]).reached) == {"x", "y"}


def test_correlated_device_loss(g):
    setup(
        g,
        [{"id": "device", "kind": "device"}],
        ["one", "two"],
        [("one", "one", ["device"], True), ("two", "two", ["device"], True)],
    )
    result = scenarios.run_scenario("test", ScenarioRequest(kind="lockout", root_ids=["device"]))
    assert ids(result) == {"one", "two"}


def test_password_needed_blocks_stranger(g):
    setup(g, [{"id": "root"}], ["x"], [("password", "x", ["root"], True)])
    assert set(closure(g, ["root"]).reached) == {"root"}
    assert set(closure(g, ["root"], pw=True).reached) == {"root", "x"}


def test_custom_domain_mx(g):
    setup(
        g,
        [{"id": "domain", "kind": "domain"}, {"id": "email", "kind": "email"}],
        ["x"],
        [("mx", "email", ["domain"], False), ("reset", "x", ["email"], False)],
    )
    result = closure(g, ["domain"])
    assert set(result.reached) == {"domain", "email", "x"}
    assert result.reached["x"].round == 2
    assert result.needs == {"email": ["domain"], "x": ["email"]}


def test_two_alternatives_choose_one_earliest_derivation(g):
    setup(g, [{"id": "a"}, {"id": "b"}], ["x"], [("z", "x", ["a", "b"], False), ("a", "x", ["a"], False)])
    result = closure(g, ["a", "b"])
    assert result.reached["x"].via_method == "a"
    assert result.needs["x"] == ["a"]


def test_lockout_complement_excludes_already_unreachable(g):
    setup(
        g,
        [{"id": "phone"}, {"id": "other", "status": "inactive"}],
        ["lost", "never"],
        [("lost", "lost", ["phone"], True), ("never", "never", ["other"], True)],
    )
    result = scenarios.run_scenario("test", ScenarioRequest(kind="lockout", root_ids=["phone"]))
    assert ids(result) == {"lost"}
    assert scenarios.get_scenario("test", result.id) == result


def test_zero_need_methods_only_with_password_and_disabled_methods(g):
    setup(
        g,
        [{"id": "root"}],
        ["allowed", "invalid"],
        [("password", "allowed", [], True), ("invalid", "invalid", [], False)],
    )
    assert set(closure(g, []).reached) == set()
    assert set(closure(g, [], pw=True).reached) == {"allowed"}
    assert set(closure(g, [], pw=True, disabled=["password"]).reached) == set()


def test_fixture_takeover_and_explain(persona):
    trace = []
    result = scenarios.run_scenario(
        "test",
        ScenarioRequest(kind="takeover", root_ids=["phone_old"]),
        trace=lambda *record: trace.append(record),
    )
    assert set(result.direct_accounts) == {"google", "x", "amazon_in", "swiggy", "zomato"}
    assert ids(result) == {
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
    }
    assert result.unknown_accounts == ["splitwise"]
    assert result.total_accounts == 17
    assert result.rounds == 3
    assert result.ms > 0
    assert scenarios.get_scenario("test", result.id) == result
    explanation = scenarios.explain("test", result.id, "dropbox")
    assert explanation.outcome == "path"
    assert [(s.from_id, s.to_id) for s in explanation.steps] == [
        ("phone_old", "google"),
        ("google", "email_primary"),
        ("email_primary", "dropbox"),
        ("phone_old", "dropbox"),
    ]
    assert {e.id for s in explanation.steps for e in s.evidence} == {"evidence_1"}
    assert scenarios.explain("test", result.id, "splitwise").outcome == "not_in_graph"
    assert scenarios.explain("test", result.id, "missing").outcome == "not_in_graph"
    assert scenarios.explain("test", result.id, "github").outcome == "not_affected"
    assert {r[0] for r in trace} >= {"closure_round", "write_scenario", "write_reached", "write_derivation"}
    assert all(record[2] >= 0 for record in trace)


def test_fixture_lockout_and_compound(persona):
    single = scenarios.run_scenario("test", ScenarioRequest(kind="lockout", root_ids=["email_college"]))
    assert ids(single) == {"figma", "canva", "coursera", "microsoft"}
    assert set(single.direct_accounts) == ids(single)
    assert scenarios.explain("test", single.id, "figma").outcome == "lost_now"
    compound = scenarios.run_scenario(
        "test", ScenarioRequest(kind="lockout", root_ids=["phone_old", "email_college"])
    )
    assert ids(compound) == {
        "google",
        "x",
        "amazon_in",
        "swiggy",
        "zomato",
        "notion",
        "spotify",
        "paypal",
        "dropbox",
        "figma",
        "canva",
        "coursera",
        "microsoft",
        "github",
    }
    assert "linkedin" not in ids(compound)
    assert "github" not in {node.node_id for node in compound.lost_now_accounts}


def test_scenario_pruning_removes_derivations(persona):
    results = [
        scenarios.run_scenario("test", ScenarioRequest(kind="takeover", root_ids=["phone_old"]))
        for _ in range(21)
    ]
    assert scenarios.get_scenario("test", results[0].id) is None
    assert db.run(persona, "explain", {"sid": results[0].id}).rows == []
    assert all(scenarios.get_scenario("test", result.id) is not None for result in results[1:])


@pytest.mark.parametrize("roots", [[], ["missing"], ["phone_old", "missing"]])
def test_reject_unknown_or_empty_roots(persona, roots):
    with pytest.raises(ValueError, match="unknown_root"):
        scenarios.run_scenario("test", ScenarioRequest(kind="takeover", root_ids=roots))


def test_closure_benchmark(persona):
    timings = [closure(persona, ["phone_old"]).ms for _ in range(5)]
    print(f"fixture closure ms: min={min(timings):.2f}, mean={sum(timings) / len(timings):.2f}")
    assert len(closure(persona, ["phone_old"]).reached) == 12


def test_lockout_distinguishes_password_login_from_recovery(g):
    setup(
        g,
        [{"id": "email_college", "kind": "email"}],
        ["mail_host", "password_login", "email_code", "no_recovery"],
        [
            ("host_password", "mail_host", [], True),
            ("mailbox", "email_college", ["mail_host"], False),
            ("login", "password_login", [], True),
            ("reset", "password_login", ["email_college"], False),
            ("code", "email_code", ["email_college"], False),
            ("password_only", "no_recovery", [], True),
        ],
    )
    result = scenarios.run_scenario("test", ScenarioRequest(kind="lockout", root_ids=["email_college"]))
    assert {node.node_id for node in result.lost_now_accounts} == {"email_code"}
    assert {node.node_id for node in result.recovery_lost_accounts} == {"email_code", "password_login"}
    assert ids(result) == {"email_code", "password_login"}
    assert scenarios.get_scenario("test", result.id) == result
    immediate = scenarios.explain("test", result.id, "email_code")
    assert immediate.outcome == "lost_now"
    assert [(step.from_id, step.to_id) for step in immediate.steps] == [
        ("mail_host", "email_college"),
        ("email_college", "email_code"),
    ]
    recovery = scenarios.explain("test", result.id, "password_login")
    assert recovery.outcome == "recovery_lost"
    assert [(step.from_id, step.to_id, step.method_id) for step in recovery.steps] == [
        ("email_college", "password_login", "reset")
    ]
    assert scenarios.explain("test", result.id, "no_recovery").outcome == "not_affected"


def test_recovery_excludes_mailbox_lost_through_second_factor(g):
    setup(
        g,
        [{"id": "phone"}, {"id": "email_primary", "kind": "email"}],
        ["mail_host", "dependent"],
        [
            ("host_login", "mail_host", ["phone"], True),
            ("mailbox", "email_primary", ["mail_host"], False),
            ("login", "dependent", [], True),
            ("reset", "dependent", ["email_primary"], False),
        ],
    )
    result = scenarios.run_scenario("test", ScenarioRequest(kind="lockout", root_ids=["phone"]))
    assert {node.node_id for node in result.lost_now_accounts} == {"mail_host"}
    assert {node.node_id for node in result.recovery_lost_accounts} == {"dependent"}
    assert ids(result) == {"mail_host", "dependent"}


def test_full_policy_lockout_tiers_and_compound(g):
    policies, _ = load_policy_file("lapse/policy/services.yaml")
    _, carriers = load_policy_file("lapse/policy/carriers.yaml")
    load_persona(g, policies, carriers)
    single = scenarios.run_scenario("test", ScenarioRequest(kind="lockout", root_ids=["email_college"]))
    assert single.lost_now_accounts == []
    assert {node.node_id for node in single.recovery_lost_accounts} == {
        "figma",
        "canva",
        "coursera",
        "microsoft",
    }
    assert set(single.direct_accounts) == ids(single)
    assert scenarios.explain("test", single.id, "figma").outcome == "recovery_lost"
    compound = scenarios.run_scenario(
        "test", ScenarioRequest(kind="lockout", root_ids=["phone_old", "email_college"])
    )
    assert ids(single) <= ids(compound)
    assert {node.node_id for node in compound.lost_now_accounts} == {
        "google",
        "dropbox",
        "paypal",
        "swiggy",
        "zomato",
    }
    assert ids(compound) == {
        node.node_id for node in [*compound.lost_now_accounts, *compound.recovery_lost_accounts]
    }
    assert "splitwise" not in ids(compound)
