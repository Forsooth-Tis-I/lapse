import json

import pytest

from lapse.contracts import ServicePolicy
from lapse.graph import db
from lapse.policy.compile import compile_user_graph, write_policy_graph

pytestmark = pytest.mark.db


@pytest.fixture
def policy():
    return ServicePolicy.model_validate(
        {
            "service": {"id": "service", "name": "Service"},
            "methods": [
                {
                    "id": "reset_email",
                    "kind": "reset",
                    "label": "Email reset without 2FA",
                    "needs_roles": ["login_email"],
                    "requires_absent_roles": ["sms_2fa", "totp_device"],
                },
                {
                    "id": "reset_email_then_sms",
                    "kind": "reset",
                    "label": "Email reset with SMS",
                    "needs_roles": ["login_email", "sms_2fa"],
                },
                {
                    "id": "reset_email_then_totp",
                    "kind": "reset",
                    "label": "Email reset with authenticator",
                    "needs_roles": ["login_email", "totp_device"],
                },
            ],
        }
    )


@pytest.fixture
def compiled_graph(isolated_graph, policy):
    isolated_graph.query(
        "CREATE (a:Account {id: 'a', service_id: 'service', identifier: 'a@example.com'}), "
        "(b:Account {id: 'b', service_id: 'service', identifier: 'b@example.com'}), "
        "(e:Root {id: 'old'}), (n:Root {id: 'new'}), "
        "(:Root:Email {id: 'mailbox_a', address: 'a@example.com', hosted_by_service: 'service'}), "
        "(:Root:Email {id: 'mailbox_b', address: 'b@example.com', hosted_by_service: 'service'}), "
        "(a)-[:USES {role: 'login_email'}]->(e), (b)-[:USES {role: 'login_email'}]->(e)"
    )
    compile_user_graph(isolated_graph, [policy])
    return isolated_graph


@pytest.mark.parametrize(
    "factor_roles, expected",
    [
        ([], ["m:a:reset_email"]),
        (["sms_2fa"], ["m:a:reset_email_then_sms"]),
        (["totp_device"], ["m:a:reset_email_then_totp"]),
        (["sms_2fa", "totp_device"], ["m:a:reset_email_then_sms", "m:a:reset_email_then_totp"]),
    ],
)
def test_absent_roles_exclude_email_only_reset(compiled_graph, policy, factor_roles, expected):
    compiled_graph.query(
        "MATCH (a:Account {id: 'a'}) UNWIND $roles AS role "
        "CREATE (r:Root {id: role}), (a)-[:USES {role: role}]->(r)",
        {"roles": factor_roles},
    )
    compile_user_graph(compiled_graph, [policy], account_ids=["a"])
    assert compiled_graph.ro_query(
        "MATCH (m:Method)-[:GRANTS]->(:Account {id: 'a'}) RETURN m.id ORDER BY m.id"
    ).result_set == [[method] for method in expected]
    assert compiled_graph.ro_query("MATCH (r)-[:ENABLES]->(:Account {id: 'a'}) RETURN r.id").result_set == (
        [] if factor_roles else [["old"]]
    )


def test_scoped_recompile_preserves_unselected_methods_mailboxes_and_enables(compiled_graph, policy):
    queries = [
        "MATCH (m:Method {account_id: 'b'}) RETURN id(m), properties(m) ORDER BY m.id",
        "MATCH (m:Method {account_id: 'b'})-[r]->(n) RETURN id(r), type(r), n.id ORDER BY id(r)",
        "MATCH (n)-[r:ENABLES]->(t) WHERE t.id IN ['b', 'mailbox_b'] RETURN id(r), n.id, t.id ORDER BY id(r)",
    ]
    before = [compiled_graph.ro_query(query).result_set for query in queries]
    compiled_graph.query(
        "MATCH (a:Account {id: 'a'})-[u:USES]->(), (n:Root {id: 'new'}) "
        "DELETE u CREATE (a)-[:USES {role: 'login_email'}]->(n)"
    )
    compile_user_graph(compiled_graph, [policy], account_ids=["a"])
    assert [compiled_graph.ro_query(query).result_set for query in queries] == before
    assert compiled_graph.ro_query(
        "MATCH (:Method {id: 'm:a:reset_email'})-[:NEEDS]->(r) RETURN r.id"
    ).result_set == [["new"]]
    assert compiled_graph.ro_query(
        "MATCH (n)-[:ENABLES]->(t) WHERE t.id IN ['a', 'mailbox_a'] RETURN n.id, t.id ORDER BY t.id"
    ).result_set == [["new", "a"], ["a", "mailbox_a"]]


def test_empty_account_filter_does_not_touch_graph(compiled_graph):
    queries = [
        "MATCH (m:Method) RETURN id(m), properties(m) ORDER BY id(m)",
        "MATCH ()-[r]->() RETURN id(r), type(r), properties(r) ORDER BY id(r)",
    ]
    before = [compiled_graph.ro_query(query).result_set for query in queries]
    compile_user_graph(compiled_graph, [], account_ids=[])
    assert [compiled_graph.ro_query(query).result_set for query in queries] == before


@pytest.mark.parametrize("removed", [False, True])
def test_scoped_recompile_removes_methods_for_closed_or_removed_account(compiled_graph, policy, removed):
    compiled_graph.query(
        "MATCH (a:Account {id: 'a'}) " + ("DETACH DELETE a" if removed else "SET a.status = 'closed'")
    )
    compile_user_graph(compiled_graph, [policy], account_ids=["a"])
    assert compiled_graph.ro_query("MATCH (m:Method {account_id: 'a'}) RETURN m.id").result_set == []
    assert (
        compiled_graph.ro_query(
            "MATCH ()-[e:ENABLES]->(t) WHERE t.id IN ['a', 'mailbox_a'] RETURN t.id"
        ).result_set
        == []
    )
    assert compiled_graph.ro_query(
        "MATCH (m:Method {account_id: 'b'}) RETURN m.id ORDER BY m.id"
    ).result_set == [["m:b:reset_email"], ["m:mailbox:mailbox_b"]]


def test_scoped_recompile_removes_closed_mailbox(compiled_graph, policy):
    compiled_graph.query("MATCH (e:Email {id: 'mailbox_a'}) SET e.status = 'closed'")
    compile_user_graph(compiled_graph, [policy], account_ids=["a"])
    assert compiled_graph.ro_query(
        "MATCH (m:Method {account_id: 'a'}) RETURN m.id ORDER BY m.id"
    ).result_set == [["m:a:reset_email"]]
    assert compiled_graph.ro_query(
        "MATCH ()-[:ENABLES]->(:Email {id: 'mailbox_a'}) RETURN count(*)"
    ).result_set == [[0]]


def test_policy_graph_can_be_selected_explicitly(isolated_graph, policy):
    write_policy_graph([policy], [], g=isolated_graph)
    assert isolated_graph.ro_query(
        "MATCH (m:MethodTemplate {template_id: 'reset_email'}) RETURN m.requires_absent_roles"
    ).result_set == [[["sms_2fa", "totp_device"]]]


def test_recompile_keeps_persisted_policy_overlay_and_account_exemptions(compiled_graph, policy, monkeypatch):
    shared = db.graph(compiled_graph.name + ":policy")
    monkeypatch.setattr(db, "policy_graph", lambda: shared)
    try:
        shared.query(
            "CREATE (:PolicyEvent {id: 'retire_email_reset', service_id: 'service', diff: $diff})",
            {
                "diff": json.dumps(
                    {
                        "disable_needs_roles": ["login_email"],
                        "exempt_account_property": "subscriber",
                    }
                )
            },
        )
        compiled_graph.query("MATCH (a:Account {id: 'b'}) SET a.subscriber = true")
        write_policy_graph([policy], [], g=shared)
        assert shared.ro_query("MATCH (e:PolicyEvent) RETURN e.id").result_set == [["retire_email_reset"]]
        for account_ids in (None, ["a", "b"]):
            traces = []
            compile_user_graph(
                compiled_graph,
                [policy],
                account_ids=account_ids,
                trace=lambda *row, traces=traces: traces.append(row),
            )
            assert compiled_graph.ro_query(
                "MATCH (m:Method)-[:GRANTS]->(a:Account) RETURN a.id, m.id ORDER BY a.id"
            ).result_set == [["b", "m:b:reset_email"]]
            assert "compile_policy_events" in [row[0] for row in traces]
    finally:
        shared.delete()


@pytest.mark.parametrize("service", ["notion", "canva"])
def test_email_confirmation_patterns_require_completed_change(service):
    import re

    from lapse.policy.loader import default_policy_paths, load_policy_file

    policy = next(
        policy
        for path in default_policy_paths()
        for policy in load_policy_file(path)[0]
        if policy.service.id == service
    )
    patterns = next(change.confirmation_patterns for change in policy.change if change.root_kind == "email")
    assert any(re.search(pattern, "Your email address has been changed") for pattern in patterns)
    assert not any(
        re.search(pattern, text)
        for pattern in patterns
        for text in (
            "Verify your new email address",
            "Your verification code to change your email address",
            "New email alias added",
            "Your email address has not been changed",
        )
    )
