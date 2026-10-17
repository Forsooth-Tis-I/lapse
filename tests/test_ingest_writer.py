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
