import sys
from datetime import UTC, date, datetime, timedelta
from types import ModuleType
from uuid import uuid4

import pytest
import yaml

from lapse.contracts import ContactChange, ExtractedEvent, GraphEvent, ServicePolicy
from lapse.graph import db
from lapse.ingest import writer
from lapse.ingest.pipeline import iter_events
from lapse.onboarding import load_persona_local

pytestmark = pytest.mark.db


@pytest.fixture
def graph(monkeypatch, tmp_path):
    g = db.graph("lapse:test:wp3b:writer:" + uuid4().hex)
    monkeypatch.setattr(db, "user_graph", lambda uid: g)
    persona = {
        "display_name": "Synthetic persona",
        "phones": [
            {
                "id": "phone_old",
                "e164": "+919999994321",
                "carrier": "Vi",
                "country": "IN",
                "status": "retiring",
                "drop_at": "2026-10-31",
            },
            {"id": "phone_new", "e164": "+919999997788", "carrier": "Jio", "country": "IN"},
        ],
        "emails": [
            {"id": "email_primary", "address": "demo@example.com", "kind": "personal", "hosted_by": "google"},
            {
                "id": "email_college",
                "address": "demo@example.edu",
                "kind": "edu",
                "hosted_by": "college_workspace",
            },
        ],
    }
    path = tmp_path / "persona.yaml"
    path.write_text(yaml.safe_dump(persona))
    load_persona_local("test", path)
    compiler = ModuleType("lapse.policy.compile")
    compiler.calls = []

    def compile_user_graph(graph, policies, *, account_ids=None):
        compiler.calls.append((graph, account_ids))

    compiler.compile_user_graph = compile_user_graph
    monkeypatch.setitem(sys.modules, "lapse.policy.compile", compiler)
    events = ModuleType("lapse.events")
    events.calls = []

    def publish(uid, kind, data):
        GraphEvent(uid=uid, type=kind, data=data, at=datetime.now(UTC))
        events.calls.append((uid, kind, data))

    events.publish = publish
    monkeypatch.setitem(sys.modules, "lapse.events", events)
    try:
        yield g, compiler, events
    finally:
        g.delete()


def event(**kwargs):
    values = {
        "msg_id": "<one>",
        "inbox": "email_primary",
        "date": datetime(2026, 10, 17, tzinfo=UTC),
        "sender": "notice@google.com",
        "sender_domain": "google.com",
        "subject": "Phone notice",
        "snippet": "Phone ending in 4321",
        "service_id": "google",
        "confidence": 0.8,
        "event": "otp_sms_notice",
        "phone_last4": ["4321"],
    }
    return ExtractedEvent(**(values | kwargs))


def uses(g, service):
    return g.ro_query(
        "MATCH (a:Account {service_id: $service})-[u:USES]->(r:Root) "
        "RETURN u.role, r.id, u.confirmed ORDER BY u.role, r.id",
        {"service": service},
    ).result_set


def snapshot(g):
    return (
        g.ro_query("MATCH (n) RETURN labels(n), properties(n) ORDER BY n.id").result_set,
        g.ro_query(
            "MATCH (a)-[e]->(b) RETURN a.id, type(e), b.id, properties(e) ORDER BY a.id, type(e), b.id"
        ).result_set,
    )


def test_corpus_roles_closure_evidence_and_replay(graph):
    g, compiler, published = graph
    events = list(iter_events(["email_primary", "email_college"], live=False, use_llm=False))
    counts = writer.write_events("test", events)
    assert counts["accounts"] == 14
    assert counts["evidence"] == 26
    assert counts["unknown_services"] == 3
    assert counts["per_service"]["google"] == 1
    assert ["recovery_phone", "phone_old", True] in uses(g, "google")
    assert ["sms_2fa", "phone_old", True] in uses(g, "google")
    assert uses(g, "amazon_in") == [
        ["login_email", "email_primary", True],
        ["login_phone", "phone_new", True],
    ]
    assert uses(g, "figma") == [["login_email", "email_primary", True]]
    assert ["login_phone", "phone_old", True] in uses(g, "microsoft")
    assert g.ro_query('MATCH (e:Email {id: "email_college"}) RETURN e.status, e.closes_at').result_set == [
        ["closing", "2026-11-15"]
    ]
    assert g.ro_query(
        'MATCH (s:Signal {kind: "closing_email"})-[:ABOUT]->(e:Email) RETURN DISTINCT e.id, s.deadline'
    ).result_set == [["email_college", "2026-11-15"]]
    assert g.ro_query("MATCH (e:Evidence)-[:SUPPORTS]->(a:Account) RETURN count(e)").result_set == [[26]]
    assert g.ro_query('MATCH (s:Signal {kind: "new_device"}) RETURN count(s)').result_set == [[2]]
    assert g.ro_query("MATCH (e:Evidence) RETURN max(size(e.snippet))").result_set[0][0] <= 300
    assert len(compiler.calls[0][1]) == 14
    assert published.calls[-1] == (
        "test",
        "ingest",
        {
            "emails_scanned": 26,
            "accounts_found": 14,
            "edges_inferred": counts["inferred_uses"],
            "edges_confirmed": counts["confirmed_uses"],
            "status": "running",
        },
    )
    writer.write_events("test", [])
    assert published.calls[-1][2]["status"] == "done"
    before = snapshot(g)
    assert writer.write_events("test", list(reversed(events))) == counts
    assert snapshot(g) == before


def test_unknown_and_ambiguous_phone_remain_inferred(graph):
    g, _, _ = graph
    writer.write_events("test", [event(phone_last4=["9999"])])
    assert g.ro_query(
        'MATCH (:Account)-[u:USES]->(p:Phone {last4: "9999"}) RETURN p.status, p.confirmed, u.confirmed'
    ).result_set == [["unknown", False, False]]
    g.query(
        'CREATE (:Root:Phone {id: "other_old", kind: "phone", label: "Other", '
        'last4: "9921", status: "active", confirmed: true})'
    )
    writer.write_events("test", [event(msg_id="<unique>", phone_last4=["4321"])])
    writer.write_events(
        "test",
        [
            event(
                msg_id="<ambiguous>",
                phone_last4=["21"],
                event="contact_changed",
                contact_change=ContactChange(kind="phone", new_last4="21"),
            )
        ],
    )
    assert ["sms_2fa", "phone_old", True] in uses(g, "google")
    assert g.ro_query(
        'MATCH (:Account)-[u:USES]->(p:Phone {last4: "21"}) RETURN p.status, p.confirmed, u.confirmed'
    ).result_set == [["unknown", False, False]]
    assert g.ro_query('MATCH (:Account)-[:USES]->(:Phone {id: "other_old"}) RETURN count(*)').result_set == [
        [0]
    ]


def test_change_survives_older_observation_and_preserves_other_roles(graph):
    g, _, _ = graph
    old = event(subject="Recovery phone", snippet="Your recovery phone ends in 4321")
    sms = event(msg_id="<sms>")
    changed = event(
        msg_id="<changed>",
        date=old.date + timedelta(days=1),
        event="contact_changed",
        subject="Recovery phone changed",
        snippet="Recovery phone changed to 7788",
        phone_last4=["4321", "7788"],
        contact_change=ContactChange(kind="phone", old_last4="4321", new_last4="7788"),
    )
    writer.write_events("test", [old, sms])
    writer.write_events("test", [changed])
    before = snapshot(g)
    writer.write_events("test", [old])
    assert snapshot(g) == before
    assert ["recovery_phone", "phone_new", True] in uses(g, "google")
    assert ["sms_2fa", "phone_old", True] in uses(g, "google")
    assert g.ro_query(
        'MATCH (e:Evidence {msg_id: "<changed>"})-[:MENTIONS]->(p:Phone) RETURN p.id ORDER BY p.id'
    ).result_set == [["phone_new"], ["phone_old"]]
    assert g.ro_query(
        'MATCH (s:Signal {kind: "policy_event"})-[:ABOUT]->(p:Phone) RETURN p.id'
    ).result_set == [["phone_old"]]


def test_unknown_service_snippet_cap_and_no_signal_reopening(graph):
    g, _, _ = graph
    incoming = event(
        service_id="unrecognised",
        service_guess="Small service",
        sender_domain="small.example",
        event="deactivation_notice",
        deadline=date(2026, 11, 15),
        phone_last4=[],
    )
    incoming = incoming.model_copy(update={"snippet": "Notice " * 100})
    writer.write_events("test", [incoming])
    assert g.ro_query("MATCH (s:Service) RETURN s.name, s.modelled").result_set == [["Small service", False]]
    assert g.ro_query("MATCH (e:Evidence) RETURN size(e.snippet)").result_set == [[300]]
    g.query('MATCH (s:Signal) SET s.status = "dismissed"')
    writer.write_events("test", [incoming])
    assert g.ro_query("MATCH (s:Signal) RETURN s.status").result_set == [["dismissed"]]


def test_phone_first_policy_and_legacy_compiler(graph, monkeypatch):
    g, compiler, _ = graph
    policy = ServicePolicy.model_validate(
        {
            "service": {"id": "phone_first", "name": "Phone first"},
            "methods": [{"id": "phone", "kind": "login", "label": "Phone", "needs_roles": ["login_phone"]}],
        }
    )
    monkeypatch.setattr(writer, "default_policy_paths", lambda: ["fake"])
    monkeypatch.setattr(writer, "load_policy_file", lambda path: ([policy], []))
    compiled = []
    compiler.compile_user_graph = lambda graph, policies: compiled.append(graph.name)
    writer.write_events("test", [event(service_id="phone_first", phone_last4=["21"])])
    assert ["login_phone", "phone_old", True] in uses(g, "phone_first")
    assert compiled == [g.name]


def test_trace_and_absent_publisher(graph, monkeypatch):
    _, _, _ = graph
    original_import = writer.import_module

    def importing(name):
        if name == "lapse.events":
            raise ModuleNotFoundError(name=name)
        return original_import(name)

    monkeypatch.setattr(writer, "import_module", importing)
    traces = []
    counts = writer.write_events("test", [event()], trace=lambda *args: traces.append(args))
    assert counts["accounts"] == 1
    assert {"ingest_account", "ingest_use", "ingest_summary"} <= {row[0] for row in traces}
    assert all(ms >= 0 and rows >= 0 for _, _, ms, rows in traces)


def test_change_without_old_value_signals_replaced_retiring_root(graph):
    g, _, _ = graph
    writer.write_events("test", [event()])
    writer.write_events(
        "test",
        [
            event(
                msg_id="<new>",
                date=datetime(2026, 10, 18, tzinfo=UTC),
                event="contact_changed",
                phone_last4=["7788"],
                contact_change=ContactChange(kind="phone", new_last4="7788"),
            )
        ],
    )
    assert ["sms_2fa", "phone_new", True] in uses(g, "google")
    assert g.ro_query(
        'MATCH (s:Signal {kind: "policy_event"})-[:ABOUT]->(p:Phone) RETURN p.id'
    ).result_set == [["phone_old"]]


@pytest.mark.parametrize("reverse", [False, True])
def test_contact_change_keeps_newer_sms_observation_in_either_delivery_order(graph, reverse):
    g, _, _ = graph
    change = event(
        msg_id="<change>",
        event="contact_changed",
        phone_last4=["7788"],
        contact_change=ContactChange(kind="phone", new_last4="7788"),
    )
    notice = event(msg_id="<later>", date=change.date + timedelta(days=1))
    for incoming in [notice, change] if reverse else [change, notice]:
        writer.write_events("test", [incoming])
    assert uses(g, "google") == [
        ["login_email", "email_primary", False],
        ["sms_2fa", "phone_new", True],
        ["sms_2fa", "phone_old", True],
    ]


def email_change(**kwargs):
    return event(
        **(
            {
                "msg_id": "<email-changed>",
                "date": datetime(2026, 10, 18, tzinfo=UTC),
                "inbox": "email_primary",
                "account_identifier": "demo@example.com",
                "service_id": "canva",
                "sender": "notice@canva.com",
                "sender_domain": "canva.com",
                "event": "contact_changed",
                "phone_last4": [],
                "subject": "Your email address has been changed",
                "snippet": "Your email address changed from demo@example.edu to demo@example.com.",
                "contact_change": ContactChange(
                    kind="email", old_email="demo@example.edu", new_email="demo@example.com"
                ),
            }
            | kwargs
        )
    )


def test_email_confirmation_preserves_fixture_identity_and_replay(graph):
    g, _, _ = graph
    g.query(
        "MATCH (old:Email {id: 'email_college'}) "
        "CREATE (a:Account {id: 'canva', service_id: 'canva', identifier: 'demo@example.edu'}), "
        "(a)-[:USES {role: 'login_email'}]->(old), "
        "(:Change {id: 'change', account_id: 'canva'})"
    )
    writer.write_events("test", [email_change()])
    assert g.ro_query("MATCH (a:Account) RETURN a.id, a.identifier").result_set == [
        ["canva", "demo@example.com"]
    ]
    assert uses(g, "canva") == [["login_email", "email_primary", True]]
    assert g.ro_query(
        "MATCH (e:Evidence)-[:SUPPORTS]->(a:Account), (c:Change {account_id: a.id}) RETURN e.msg_id, c.id"
    ).result_set == [["<email-changed>", "change"]]
    before = snapshot(g)
    writer.write_events("test", [email_change()])
    assert snapshot(g) == before


@pytest.mark.parametrize("reverse", [False, True])
def test_email_identity_and_uses_survive_out_of_order_signup(graph, reverse):
    g, _, _ = graph
    signup = email_change(
        msg_id="<signup>",
        date=datetime(2026, 10, 17, tzinfo=UTC),
        event="signup",
        inbox="email_college",
        account_identifier="demo@example.edu",
        contact_change=None,
    )
    ordered = [signup, email_change()]
    for incoming in reversed(ordered) if reverse else ordered:
        writer.write_events("test", [incoming])
    assert g.ro_query("MATCH (a:Account) RETURN a.identifier").result_set == [["demo@example.com"]]
    assert uses(g, "canva") == [["login_email", "email_primary", True]]
    assert g.ro_query("MATCH (:Evidence)-[:SUPPORTS]->(a) RETURN count(DISTINCT a)").result_set == [[1]]


def test_ambiguous_email_change_does_not_merge_two_accounts(graph):
    g, _, _ = graph
    g.query(
        "CREATE (:Account {id: 'old', service_id: 'canva', identifier: 'demo@example.edu'}), "
        "(:Account {id: 'new', service_id: 'canva', identifier: 'demo@example.com'})"
    )
    before = snapshot(g)
    with pytest.raises(ValueError, match="Ambiguous account identity"):
        writer.write_events("test", [email_change()])
    assert snapshot(g) == before


def test_confirmation_without_old_email_resolves_pending_change(graph):
    g, _, _ = graph
    g.query(
        "MATCH (old:Email {id: 'email_college'}) "
        "CREATE (a:Account {id: 'canva', service_id: 'canva', identifier: 'demo@example.edu'}), "
        "(a)-[:USES {role: 'login_email'}]->(old), "
        "(:Change {id: 'change', account_id: 'canva', role: 'login_email', "
        "to_root: 'email_primary', status: 'awaiting_user'})"
    )
    writer.write_events(
        "test", [email_change(contact_change=ContactChange(kind="email", new_email="demo@example.com"))]
    )
    assert g.ro_query("MATCH (a:Account) RETURN a.id, a.identifier").result_set == [
        ["canva", "demo@example.com"]
    ]
    assert uses(g, "canva") == [["login_email", "email_primary", True]]


def test_unattributed_email_change_does_not_guess_the_existing_account(graph):
    g, _, _ = graph
    g.query("CREATE (:Account {id: 'canva', service_id: 'canva', identifier: 'other@example.edu'})")
    before = snapshot(g)
    with pytest.raises(ValueError, match="Unresolved account identity"):
        writer.write_events(
            "test", [email_change(contact_change=ContactChange(kind="email", new_email="demo@example.com"))]
        )
    assert snapshot(g) == before


@pytest.mark.parametrize("current_email", ["demo@example.edu", "demo@example.com"])
def test_explicit_old_email_cannot_be_overridden_by_pending_target(graph, current_email):
    g, _, _ = graph
    g.query(
        "CREATE (:Account {id: 'canva', service_id: 'canva', identifier: $identifier}), "
        "(:Change {id: 'change', account_id: 'canva', role: 'login_email', "
        "to_root: 'email_primary', status: 'awaiting_user'})",
        {"identifier": current_email},
    )
    before = snapshot(g)
    with pytest.raises(ValueError, match="Unresolved account identity"):
        writer.write_events(
            "test",
            [
                email_change(
                    contact_change=ContactChange(
                        kind="email", old_email="someone-else@example.edu", new_email="demo@example.com"
                    )
                )
            ],
        )
    assert snapshot(g) == before


def test_recovery_email_change_preserves_login_identifier(graph):
    g, _, _ = graph
    writer.write_events(
        "test",
        [
            email_change(
                event="signup",
                contact_change=None,
                inbox="email_college",
                account_identifier="demo@example.edu",
            )
        ],
    )
    writer.write_events(
        "test",
        [
            email_change(
                msg_id="<recovery>",
                inbox="email_college",
                account_identifier="demo@example.edu",
                subject="Recovery email address has been changed",
                snippet="Recovery email changed to demo@example.com.",
            )
        ],
    )
    assert g.ro_query("MATCH (a:Account) RETURN a.identifier").result_set == [["demo@example.edu"]]
    assert uses(g, "canva") == [
        ["login_email", "email_college", True],
        ["recovery_email", "email_primary", True],
    ]


def test_support_mentions_do_not_create_email_roots(graph):
    g, _, _ = graph
    before = g.ro_query("MATCH (r:Root) RETURN r.id ORDER BY r.id").result_set
    writer.write_events(
        "test", [event(emails_mentioned=["support@google.com", "notice@google.com", " DEMO@EXAMPLE.EDU "])]
    )
    assert g.ro_query("MATCH (r:Root) RETURN r.id ORDER BY r.id").result_set == before
    assert g.ro_query("MATCH (:Evidence)-[:MENTIONS]->(e:Email) RETURN e.id ORDER BY e.id").result_set == [
        ["email_college"],
        ["email_primary"],
    ]


def test_same_service_accounts_have_distinct_display_labels(graph, monkeypatch):
    from lapse.graph import views

    g, _, _ = graph
    monkeypatch.setattr(views, "user_graph", lambda uid: g)
    writer.write_events("test", [event(), event(msg_id="<college>", inbox="email_college")])
    payload = views.graph_view("test")
    accounts = [node for node in payload["nodes"] if node["node_type"] == "Account"]
    assert {node["label"] for node in accounts} == {"Google · demo@example.com", "Google · demo@example.edu"}
    for node in accounts:
        assert views.account_detail("test", node["id"])["account"]["display"] == node["label"]


def test_security_notice_to_a_recovery_inbox_stays_on_the_owning_account(graph):
    g, _, _ = graph
    g.query(
        "MATCH (college:Email {id: 'email_college'}) "
        "CREATE (a:Account {id: 'ms', service_id: 'microsoft', identifier: 'demo@example.org'}), "
        "(a)-[:USES {role: 'recovery_email', confirmed: true}]->(college)"
    )
    notice = email_change(
        inbox="email_college",
        account_identifier="demo@example.edu",
        service_id="microsoft",
        sender="account-security-noreply@accountprotection.microsoft.com",
        sender_domain="microsoft.com",
        subject="Microsoft account security info was added",
        snippet="The following security info was recently added to the account de**o@example.org.",
        contact_change=ContactChange(kind="email", new_email="de**o@example.org"),
    )
    writer.write_events(
        "test",
        [
            notice,
            event(**{**notice.model_dump(), "msg_id": "<other>", "event": "other", "contact_change": None}),
        ],
    )
    assert g.ro_query("MATCH (a:Account) RETURN a.id").result_set == [["ms"]]
    assert uses(g, "microsoft") == [["recovery_email", "email_college", True]]
    assert g.ro_query("MATCH (r:Email) WHERE r.address CONTAINS '*' RETURN count(r)").result_set == [[0]]
    assert g.ro_query("MATCH (:Evidence)-[:SUPPORTS]->(a:Account {id: 'ms'}) RETURN count(*)").result_set == [
        [2]
    ]


@pytest.mark.parametrize("kind", ["otp_email", "contact_changed"])
@pytest.mark.parametrize("legacy", [False, True])
def test_recovery_evidence_replay_preserves_roles_and_compiled_methods(graph, monkeypatch, kind, legacy):
    g, _, _ = graph
    monkeypatch.delitem(sys.modules, "lapse.policy.compile")
    g.query(
        "MATCH (college:Email {id:'email_college'}) "
        "CREATE (a:Account {id:'ms', service_id:'microsoft', identifier:'demo@example.org'}), "
        "(a)-[:USES {role:'recovery_email', confirmed:true}]->(college)"
    )
    notice = event(
        inbox="email_college",
        account_identifier="demo@example.edu",
        service_id="microsoft",
        event=kind,
        phone_last4=[],
        sender="notice@microsoft.com",
        sender_domain="microsoft.com",
        subject="Microsoft account security info was added" if kind == "contact_changed" else "Sign-in code",
        snippet="Security information for de**o@example.org.",
        contact_change=ContactChange(kind="email", new_email="de**o@example.org")
        if kind == "contact_changed"
        else None,
    )
    writer.write_events("test", [notice, notice])
    baseline = snapshot(g)
    assert g.ro_query("MATCH (m:Method) RETURN count(m)").result_set[0][0] > 0
    if legacy:
        g.query("MATCH (e:Evidence) REMOVE e.inbox_role")
    writer.write_events("test", [notice])
    writer.write_events("test", [notice])
    assert snapshot(g) == baseline
    assert uses(g, "microsoft") == [["recovery_email", "email_college", True]]
    assert g.ro_query("MATCH (e:Evidence) RETURN e.inbox_role").result_set == [["recovery_email"]]


def test_recorded_recovery_attribution_survives_removed_dependency(graph):
    g, _, _ = graph
    g.query(
        "MATCH (r:Root {id:'email_college'}) "
        "CREATE (a:Account {id:'ms', service_id:'microsoft', identifier:'demo@example.org'}), "
        "(a)-[:USES {role:'recovery_email', confirmed:true}]->(r)"
    )
    notice = event(inbox="email_college", service_id="microsoft", event="otp_email", phone_last4=[])
    writer.write_events("test", [notice])
    g.query("MATCH (:Account)-[u:USES {role:'recovery_email'}]->() DELETE u")
    writer.write_events("test", [notice])
    assert uses(g, "microsoft") == [["recovery_email", "email_college", False]]


def test_login_inbox_replay_is_idempotent(graph):
    g, _, _ = graph
    notice = event(event="otp_email", phone_last4=[])
    writer.write_events("test", [notice])
    before = snapshot(g)
    writer.write_events("test", [notice, notice])
    assert snapshot(g) == before
    assert uses(g, "google") == [["login_email", "email_primary", True]]


def test_ambiguous_recovery_owner_is_rejected(graph):
    g, _, _ = graph
    g.query(
        "MATCH (r:Root {id:'email_college'}) "
        "CREATE (a:Account {id:'one', service_id:'microsoft', identifier:'one@example.org'}), "
        "(b:Account {id:'two', service_id:'microsoft', identifier:'two@example.org'}), "
        "(a)-[:USES {role:'recovery_email'}]->(r), (b)-[:USES {role:'recovery_email'}]->(r)"
    )
    before = snapshot(g)
    with pytest.raises(ValueError, match="Ambiguous recovery account identity"):
        writer.write_events(
            "test", [event(inbox="email_college", service_id="microsoft", event="otp_email", phone_last4=[])]
        )
    assert snapshot(g) == before
