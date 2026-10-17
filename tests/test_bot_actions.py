from datetime import UTC, datetime

import pytest

from lapse.bot import actions
from lapse.contracts import ServicePolicy
from lapse.graph import db
from lapse.policy import loader
from lapse.policy.compile import compile_user_graph

pytestmark = pytest.mark.db


@pytest.fixture
def bot_graph(isolated_graph, monkeypatch):
    g = isolated_graph
    monkeypatch.setattr(db, "user_graph", lambda uid: g)
    policy = ServicePolicy.model_validate(
        {
            "service": {"id": "service", "name": "Service"},
            "methods": [
                {"id": "sms", "kind": "reset", "label": "Phone reset", "needs_roles": ["recovery_phone"]}
            ],
        }
    )
    monkeypatch.setattr(loader, "default_policy_paths", lambda: ["synthetic"])
    monkeypatch.setattr(loader, "load_policy_file", lambda path: ([policy], []))
    g.query(
        "CREATE (r:Root:Phone {id: 'r'}), (other:Root:Phone {id: 'other'}), "
        "(a:Account {id: 'a', service_id: 'service'}), (b:Account {id: 'b', service_id: 'service'}), "
        "(a)-[:USES {role: 'recovery_phone', confirmed: false}]->(r), "
        "(a)-[:USES {role: 'sms_2fa', confirmed: false}]->(r), "
        "(b)-[:USES {role: 'recovery_phone', confirmed: false}]->(other)"
    )
    compile_user_graph(g, [policy])
    return g


def test_confirmation_and_removal_recompile_only_selected_account(bot_graph):
    g = bot_graph
    before = g.ro_query("MATCH (m:Method {account_id: 'b'}) RETURN id(m), properties(m)").result_set
    trace = []
    actions.confirm_use("u", "a", "r", "recovery_phone", True, trace=lambda *args: trace.append(args))
    assert g.ro_query(
        "MATCH (:Account {id: 'a'})-[u:USES {role: 'recovery_phone'}]->(:Root {id: 'r'}) "
        "RETURN u.confirmed, u.confidence"
    ).result_set == [[True, 1.0]]
    assert trace[0][0] == "bot_confirm_use"
    actions.confirm_use("u", "a", "r", "recovery_phone", False)
    assert g.ro_query("MATCH (:Account {id: 'a'})-[u:USES]->() RETURN u.role").result_set == [["sms_2fa"]]
    assert g.ro_query("MATCH (m:Method {account_id: 'a'}) RETURN m.id").result_set == []
    assert g.ro_query("MATCH (m:Method {account_id: 'b'}) RETURN id(m), properties(m)").result_set == before


def test_wrong_role_and_non_boolean_confirmation_do_not_mutate(bot_graph):
    with pytest.raises(ValueError, match="not found"):
        actions.confirm_use("u", "a", "r", "login_phone", True)
    with pytest.raises(ValueError, match="yes or no"):
        actions.confirm_use("u", "a", "r", "recovery_phone", "false")
    assert bot_graph.ro_query("MATCH (:Account {id: 'a'})-[u:USES]->() RETURN u.confirmed").result_set == [
        [False],
        [False],
    ]


def test_list_and_dismiss_signals(bot_graph):
    g = bot_graph
    g.query(
        "CREATE (:Signal {id: 'signal', kind: 'stale_root', root_id: 'r', at: $at, "
        "title: 'Check old number', detail: 'Still receives codes', deadline: '2026-10-31', status: 'open'})",
        {"at": datetime.now(UTC).isoformat()},
    )
    assert [signal.title for signal in actions.list_signals("u")] == ["Check old number"]
    actions.dismiss_signal("u", "signal")
    assert actions.list_signals("u") == []
    with pytest.raises(ValueError, match="not found"):
        actions.dismiss_signal("u", "missing")


def test_read_change_without_replacement_root(bot_graph):
    bot_graph.query(
        "CREATE (:Change {id: 'c', plan_id: 'p', order: 1, account_id: 'a', account_label: 'Service', "
        "role: 'recovery_phone', from_root: 'r', tier: 2, requires_old_root: true, status: 'awaiting_otp'})"
    )
    change = actions.get_change("u", "c")
    assert change.to_root is None
    assert change.account_label == "Service"
