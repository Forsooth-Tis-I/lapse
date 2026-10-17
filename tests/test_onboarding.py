from uuid import uuid4

import pytest
import yaml
from redis.exceptions import ResponseError

from lapse import onboarding
from lapse.graph import db


@pytest.fixture
def onboarding_graph(monkeypatch):
    g = db.graph(f"lapse:test:wp3b:onboarding:{uuid4().hex}")
    monkeypatch.setattr(onboarding.db, "user_graph", lambda uid: g)
    try:
        yield g
    finally:
        try:
            g.delete()
        except ResponseError as exc:
            if "Invalid graph operation on empty key" not in str(exc):
                raise


@pytest.mark.db
def test_persona_roots_are_normalized_and_idempotent(tmp_path, onboarding_graph):
    path = tmp_path / "persona.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "display_name": "Synthetic persona",
                "phones": [
                    {
                        "id": "phone_old",
                        "e164": "+919999994321",
                        "carrier": "vI",
                        "country": "IN",
                        "status": "retiring",
                        "drop_at": "2026-10-31",
                    },
                    {"id": "phone_new", "e164": "+919999997788", "carrier": "jio_in", "country": "IN"},
                    {
                        "id": "phone_unknown",
                        "last4": "8899",
                        "carrier": "Unknown",
                        "country": "IN",
                        "drop_at": "2026-10-31",
                    },
                ],
                "emails": [
                    {
                        "id": "email_primary",
                        "address": "demo@example.com",
                        "kind": "personal",
                        "hosted_by": "google",
                    },
                    {
                        "id": "email_college",
                        "address": "student@example.edu",
                        "kind": "edu",
                        "hosted_by": "college_workspace",
                        "status": "closing",
                        "closes_at": "2026-11-15",
                    },
                ],
                "devices": [{"id": "device_phone", "name": "Main phone", "kind": "phone"}],
            }
        )
    )
    queries = []
    counts = onboarding.load_persona_local("fake", path, trace=lambda name, *_: queries.append(name))
    assert counts == {"users": 1, "roots": 6, "phones": 3, "emails": 2, "devices": 1}
    assert onboarding.load_persona_local("fake", path) == counts
    assert set(queries) == {"onboarding_user", "onboarding_phone", "onboarding_email", "onboarding_device"}
    assert onboarding_graph.ro_query("MATCH (u:User) RETURN u.uid, u.name").result_set == [
        ["fake", "Synthetic persona"]
    ]
    assert onboarding_graph.ro_query("MATCH (r:Root) RETURN count(r)").result_set == [[6]]
    assert onboarding_graph.ro_query(
        "MATCH (p:Phone {id: 'phone_old'}) RETURN p.label, p.last4, p.carrier, p.reissue_after, p.confirmed"
    ).result_set == [["••4321 (Vi)", "4321", "vi_in", "2027-01-29", True]]
    assert onboarding_graph.ro_query(
        "MATCH (p:Phone {id: 'phone_new'}) RETURN p.carrier, p.status"
    ).result_set == [["jio_in", "active"]]
    assert onboarding_graph.ro_query(
        "MATCH (p:Phone {id: 'phone_unknown'}) RETURN p.reissue_after"
    ).result_set == [[None]]
    assert onboarding_graph.ro_query(
        "MATCH (e:Email {id: 'email_college'}) "
        "RETURN e.kind, e.email_kind, e.hosted_by_service, e.status, e.closes_at"
    ).result_set == [["email", "edu", "college_workspace", "closing", "2026-11-15"]]
    assert onboarding_graph.ro_query("MATCH (d:Device) RETURN d.kind, d.device_kind, d.name").result_set == [
        ["device", "phone", "Main phone"]
    ]


def test_duplicate_root_ids_fail_before_writing(tmp_path, monkeypatch):
    path = tmp_path / "persona.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "devices": [
                    {"id": "duplicate", "name": "Phone", "kind": "phone"},
                    {"id": "duplicate", "name": "Laptop", "kind": "laptop"},
                ]
            }
        )
    )
    monkeypatch.setattr(
        onboarding.db, "user_graph", lambda uid: pytest.fail("Must validate before graph writes")
    )
    with pytest.raises(ValueError, match="root ids must be unique"):
        onboarding.load_persona_local("fake", path)


@pytest.mark.db
def test_changing_to_unknown_carrier_clears_derived_date(tmp_path, onboarding_graph):
    path = tmp_path / "persona.yaml"
    phone = {"id": "phone", "last4": "4321", "carrier": "Vi", "country": "IN", "drop_at": "2026-10-31"}
    path.write_text(yaml.safe_dump({"phones": [phone]}))
    onboarding.load_persona_local("fake", path)
    assert onboarding_graph.ro_query("MATCH (p:Phone) RETURN p.reissue_after").result_set == [["2027-01-29"]]
    phone["carrier"] = "Unknown"
    path.write_text(yaml.safe_dump({"phones": [phone]}))
    onboarding.load_persona_local("fake", path)
    assert onboarding_graph.ro_query("MATCH (p:Phone) RETURN p.reissue_after").result_set == [[None]]


@pytest.mark.db
def test_reloading_persona_keeps_discovered_closure(tmp_path, onboarding_graph):
    path = tmp_path / "persona.yaml"
    path.write_text(yaml.safe_dump({"emails": [{"id": "email", "address": "demo@example.com"}]}))
    onboarding.load_persona_local("fake", path)
    onboarding_graph.query("MATCH (e:Email) SET e.status = 'closing', e.closes_at = '2026-11-15'")
    onboarding.load_persona_local("fake", path)
    assert onboarding_graph.ro_query("MATCH (e:Email) RETURN e.status, e.closes_at").result_set == [
        ["closing", "2026-11-15"]
    ]


@pytest.mark.db
def test_observed_closure_overrides_explicit_stale_persona(tmp_path, onboarding_graph):
    path = tmp_path / "persona.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "emails": [
                    {
                        "id": "email",
                        "address": "demo@example.com",
                        "status": "active",
                        "closes_at": "2026-10-01",
                    }
                ]
            }
        )
    )
    onboarding.load_persona_local("fake", path)
    onboarding_graph.query(
        "MATCH (e:Email) SET e.status = 'closing', e.closes_at = '2026-11-15', "
        "e.closing_order = '2026-10-17T00:00:00+00:00|notice'"
    )
    onboarding.load_persona_local("fake", path)
    assert onboarding_graph.ro_query("MATCH (e:Email) RETURN e.status, e.closes_at").result_set == [
        ["closing", "2026-11-15"]
    ]


@pytest.mark.db
def test_email_normalization_matches_compiler_mailbox_lookup(tmp_path, onboarding_graph):
    path = tmp_path / "persona.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "emails": [
                    {
                        "id": "email",
                        "address": "  Demo@Example.COM  ",
                        "hosted_by": "google",
                    }
                ]
            }
        )
    )
    onboarding.load_persona_local("fake", path)
    onboarding_graph.query(
        "CREATE (:Account {id: 'google-account', service_id: 'google', "
        "identifier: 'demo@example.com', status: 'active'})"
    )
    assert db.run(onboarding_graph, "compile_mailboxes").rows == [
        {"email_id": "email", "account_id": "google-account"}
    ]
    assert onboarding_graph.ro_query("MATCH (e:Email) RETURN e.address, e.label").result_set == [
        ["demo@example.com", "demo@example.com"]
    ]


@pytest.mark.parametrize(
    "section,root",
    [
        ("phones", {"e164": "+919999994321"}),
        ("emails", {"address": "private-demo@example.com"}),
    ],
)
def test_root_validation_traceback_hides_private_values(tmp_path, section, root):
    import traceback

    path = tmp_path / "persona.yaml"
    path.write_text(yaml.safe_dump({section: [root]}))
    with pytest.raises(ValueError) as error:
        onboarding.load_persona_local("fake", path)
    diagnostic = "".join(traceback.format_exception(error.value))
    assert "+919999994321" not in diagnostic
    assert "private-demo@example.com" not in diagnostic
    assert "ValidationError" not in diagnostic
    assert error.value.__suppress_context__


def test_yaml_syntax_traceback_hides_private_values(tmp_path):
    import traceback

    path = tmp_path / "persona.yaml"
    path.write_text('emails: ["private-demo@example.com", "+919999994321"\n')
    with pytest.raises(ValueError) as error:
        onboarding.load_persona_local("fake", path)
    diagnostic = "".join(traceback.format_exception(error.value))
    assert "+919999994321" not in diagnostic
    assert "private-demo@example.com" not in diagnostic
    assert "ParserError" not in diagnostic
    assert error.value.__suppress_context__
