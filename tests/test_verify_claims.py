from types import SimpleNamespace

import pytest

from scripts import verify_claims as verifier


def marker(key, value):
    return f"<!-- claim:{key} -->{value}<!-- /claim -->"


def test_checks_repeated_claims_and_preserves_surrounding_markdown():
    text = f"Before **{marker('tools.count', 1)}** and {marker('tools.count', 1)}.\n"
    with pytest.raises(ValueError, match="tools.count: documented"):
        verifier.render_claims(text, {"tools.count": 11})
    updated = verifier.render_claims(text, {"tools.count": 11}, write=True)
    assert updated == f"Before **{marker('tools.count', 11)}** and {marker('tools.count', 11)}.\n"
    assert verifier.render_claims(updated, {"tools.count": 11}) == updated


@pytest.mark.parametrize(
    "text",
    [
        "<!-- claim:tools.count -->11",
        "<!-- /claim -->",
        "<!-- claim:tools.count -->11<!-- claim:tools.count -->11<!-- /claim -->",
        "<!-- claim: -->11<!-- /claim -->",
        "<!--claim:tools.count -->11<!-- /claim -->",
        "<!-- claim:tools.count -->11<!-- /claim-->",
        "<!-- claim:tools.count",
    ],
)
def test_rejects_malformed_markers(text):
    with pytest.raises(ValueError):
        verifier.parse_claims(text)


@pytest.mark.parametrize("write", [False, True])
def test_rejects_unknown_claim_even_when_writing(write):
    with pytest.raises(ValueError, match="Unknown claim: typo.full"):
        verifier.render_claims(marker("typo.full", 0), {"tools.count": 11}, write=write)


def test_old_lockout_shape_reports_current_loss_but_not_unmeasured_recovery():
    values = verifier.scenario_claims("lockout_email_college", SimpleNamespace(affected_accounts=["a", "b"]))
    assert values == {
        "lockout_email_college.full": 2,
        "lockout_email_college.lost_now": 2,
        "lockout_email_college.recovery_lost": None,
    }
    text = marker("lockout_email_college.recovery_lost", 0)
    with pytest.raises(ValueError, match="documented '0'"):
        verifier.render_claims(text, values)
    assert verifier.render_claims(text, values, write=True) == marker(
        "lockout_email_college.recovery_lost", "not reported"
    )
    verifier.render_claims(marker("lockout_email_college.recovery_lost", "not reported"), values)


@pytest.mark.parametrize("suffix", ["", "_accounts"])
def test_future_loss_fields_take_precedence_over_legacy_affected_accounts(suffix):
    result = SimpleNamespace(
        affected_accounts=["a", "b"],
        **{
            f"lost_now{suffix}": [],
            f"recovery_lost{suffix}": ["a", "b", "c"],
        },
    )
    values = verifier.scenario_claims("compound_lockout", result)
    assert values["compound_lockout.lost_now"] == 0
    assert values["compound_lockout.recovery_lost"] == 3


def test_future_numeric_loss_fields():
    values = verifier.scenario_claims(
        "compound_lockout", SimpleNamespace(affected_accounts=[], lost_now=0, recovery_lost=4)
    )
    assert values["compound_lockout.lost_now"] == 0
    assert values["compound_lockout.recovery_lost"] == 4


@pytest.mark.parametrize(
    ("expected", "actual", "valid"),
    [
        ("0-10", 4.7, True),
        ("0–10", 10, True),
        ("0-10", 10.01, False),
        ("4-10", 3, False),
        ("10-0", 5, False),
        ("2", 2.8, True),
        ("2", 5, False),
        ("fast", 2, False),
    ],
)
def test_latency_tolerance_is_bounded(expected, actual, valid):
    assert verifier.matches("closure.ms", expected, actual) is valid


def test_latency_write_uses_rounded_band():
    assert verifier.format_value("closure.ms", 1.2) == "0-10"
    assert verifier.format_value("closure.ms", 12.2) == "0-30"
    assert verifier.matches("closure.ms", verifier.format_value("closure.ms", 12.2), 12.2)


def test_write_validates_all_files_before_changing_any(tmp_path):
    first, second = tmp_path / "first.md", tmp_path / "second.md"
    first.write_text(marker("tools.count", 1))
    second.write_text(marker("unknown.count", 1))
    with pytest.raises(ValueError, match="Unknown claim"):
        verifier.verify_files([first, second], {"tools.count": 11}, write=True)
    assert first.read_text() == marker("tools.count", 1)
    second.write_text(marker("tools.count", 2))
    assert verifier.verify_files([first, second], {"tools.count": 11}, write=True) == 2
    assert first.read_text() == second.read_text() == marker("tools.count", 11)
    assert verifier.verify_files([first, second], {"tools.count": 11}) == 2


def test_query_inventory_requires_exact_description_coverage(tmp_path):
    (tmp_path / "z.cypher").write_text("RETURN 1")
    (tmp_path / "a.cypher").write_text("RETURN 2")
    descriptions = tmp_path / "descriptions.json"
    descriptions.write_text('{"a":"Read A", "extra":"Wrong"}')
    with pytest.raises(ValueError, match="missing=\\['z'\\], extra=\\['extra'\\]"):
        verifier.query_inventory(tmp_path, descriptions)
    descriptions.write_text('{"z":"Read Z", "a":"Read A"}')
    inventory = verifier.query_inventory(tmp_path, descriptions)
    assert inventory == (
        "\n| Named query | Description |\n| --- | --- |\n"
        "| [a](lapse/graph/queries/a.cypher) | Read A |\n"
        "| [z](lapse/graph/queries/z.cypher) | Read Z |\n"
    )
    text = "before\n<!-- query-inventory -->old<!-- /query-inventory -->\nafter"
    with pytest.raises(ValueError, match="Query inventory differs"):
        verifier.render_inventory(text, inventory)
    updated = verifier.render_inventory(text, inventory, write=True)
    assert verifier.render_inventory(updated, inventory) == updated
    assert updated.startswith("before\n") and updated.endswith("\nafter")


@pytest.mark.parametrize(
    "text",
    [
        "<!-- query-inventory -->",
        "<!-- /query-inventory --><!-- query-inventory -->",
        "<!-- query-inventory --><!-- query-inventory --><!-- /query-inventory -->",
    ],
)
def test_rejects_broken_inventory_markers(text):
    with pytest.raises(ValueError):
        verifier.render_inventory(text, "table", write=True)


def test_default_fixture_uses_private_user_and_deletes_it(monkeypatch):
    graph = SimpleNamespace(name="lapse:u:private", delete=lambda: calls.append("delete"))
    calls = []
    monkeypatch.setattr(verifier.db, "user_graph", lambda uid: calls.append(uid) or graph)
    monkeypatch.setattr(verifier, "load_policy_file", lambda path: ([], []))
    monkeypatch.setattr(verifier, "load_persona", lambda *args: calls.append("fixture"))
    with pytest.raises(RuntimeError, match="evaluation failed"), verifier.verification_user(None) as uid:
        assert uid.startswith("verify-claims-")
        raise RuntimeError("evaluation failed")
    assert calls == [uid, "fixture", "delete"]


def test_existing_uid_is_copied_and_only_copy_deleted(monkeypatch):
    deleted = []
    copied = []
    monkeypatch.setattr(
        verifier.db,
        "user_graph",
        lambda uid: SimpleNamespace(name=f"lapse:u:{uid}", delete=lambda: deleted.append(uid)),
    )
    monkeypatch.setattr(
        verifier.db, "copy_graph", lambda source, target: copied.append((source.name, target))
    )
    monkeypatch.setattr(verifier, "load_persona", lambda *args: pytest.fail("must not reload existing user"))
    with verifier.verification_user("existing") as uid:
        assert uid != "existing"
    assert copied == [("lapse:u:existing", f"lapse:u:{uid}")]
    assert deleted == [uid]


@pytest.mark.db
def test_fixture_claims_from_real_graph():
    with verifier.verification_user(None) as uid:
        values = verifier.collect_claims(uid)
    assert values["takeover_phone_old.direct"] == 5
    assert values["takeover_phone_old.full"] == 10
    assert values["takeover_phone_old.unknown"] == 1
    # Two-level lockout: full is the union of lost_now and recovery_lost.
    assert values["lockout_email_college.lost_now"] == 1
    assert values["lockout_email_college.recovery_lost"] == 4
    assert values["lockout_email_college.full"] == 5
    assert values["compound_lockout.lost_now"] == 6
    assert values["compound_lockout.recovery_lost"] == 14
    assert values["compound_lockout.full"] == 15
    assert values["plan_phone_old.before"] == 11  # combined takeover + lockout exposure
    assert values["plan_phone_old.after"] == 0
    assert values["plan_phone_old.steps"] == 7
    assert values["closure.ms"] > 0


def test_inventory_prose_does_not_require_markers():
    text = "The query-inventory markers delimit the generated table."
    assert verifier.render_inventory(text, "table") == text
    assert verifier.render_inventory(text, "table", write=True) == text
