import sys
from types import ModuleType

import pytest

from lapse import onboarding
from lapse.ingest import jobs, pipeline


@pytest.fixture
def fake_writer(monkeypatch):
    module = ModuleType("lapse.ingest.writer")
    calls = []
    summary = {
        "accounts": 2,
        "uses": 3,
        "confirmed_uses": 2,
        "inferred_uses": 1,
        "signals": 1,
        "unknown_services": 1,
        "per_service": {"google": 1, "unknown": 1},
    }

    def write_events(uid, events):
        calls.append((uid, events))
        return summary

    module.write_events = write_events
    monkeypatch.setitem(sys.modules, "lapse.ingest.writer", module)
    return module, calls, summary


def test_job_onboards_then_writes_before_advancing(tmp_path, monkeypatch, fake_writer):
    _, calls, summary = fake_writer
    persona = tmp_path / "persona.yaml"
    persona.write_text("{}")
    order = []
    monkeypatch.setattr(onboarding, "load_persona_local", lambda uid, path: order.append("onboard"))

    def events(inboxes, **kwargs):
        assert order == ["onboard"]
        assert inboxes == ["email_primary", "email_college"]
        assert kwargs == {"live": False, "eml_dir": "fixtures", "use_llm": False}
        yield "first"
        assert calls == [("fake", ["first"])]
        yield "second"
        assert calls[-1] == ("fake", ["second"])
        order.append("checkpoint")

    monkeypatch.setattr(pipeline, "iter_events", events)
    assert (
        jobs.handle_ingest_run(
            "fake",
            {
                "persona_path": persona,
                "eml_dir": "fixtures",
                "no_llm": True,
            },
        )
        == summary
    )
    assert order == ["onboard", "checkpoint"]
    assert calls == [("fake", ["first"]), ("fake", ["second"]), ("fake", [])]


@pytest.mark.parametrize("fail_write", [False, True])
def test_limit_and_failure_leave_source_unacknowledged(tmp_path, monkeypatch, fake_writer, fail_write):
    module, calls, summary = fake_writer
    state = []

    def events(*args, **kwargs):
        try:
            yield "first"
            state.append("advanced")
            yield "second"
            state.append("checkpoint")
        finally:
            state.append("closed")

    monkeypatch.setattr(pipeline, "iter_events", events)
    payload = {"persona_path": tmp_path / "missing", "live": True, "limit": 1}
    if fail_write:

        def fail(*args):
            raise RuntimeError("write failed")

        module.write_events = fail
        with pytest.raises(RuntimeError, match="write failed"):
            jobs.handle_ingest_run("fake", payload)
    else:
        assert jobs.handle_ingest_run("fake", payload) == summary
        assert calls == [("fake", ["first"]), ("fake", [])]
    assert state == ["closed"]


@pytest.mark.parametrize("source", ["--eml-dir", "--live"])
@pytest.mark.parametrize("explicit_persona", [False, True])
def test_cli_prints_only_summary(monkeypatch, capsys, tmp_path, source, explicit_persona):
    from scripts import ingest_live

    summary = {
        "accounts": 2,
        "uses": 3,
        "confirmed_uses": 2,
        "inferred_uses": 1,
        "signals": 1,
        "unknown_services": 1,
        "per_service": {"google": 2},
        "private": "secret@example.com",
    }
    argv = ["ingest_live.py", "--uid", "fake", source]
    if source == "--eml-dir":
        argv.append("fixtures")
    argv.append("--no-llm")
    persona = tmp_path / "custom.yaml"
    if explicit_persona:
        argv.extend(["--persona", str(persona)])
    monkeypatch.setattr(sys, "argv", argv)
    calls = []

    def handle(uid, payload):
        calls.append((uid, payload))
        return summary

    monkeypatch.setattr(ingest_live, "handle_ingest_run", handle)
    ingest_live.main()
    assert calls[0][0] == "fake"
    assert calls[0][1]["live"] is (source == "--live")
    expected_persona = (
        persona
        if explicit_persona
        else jobs.ROOT_DIR
        / ("tests/fixtures/persona.test.yaml" if source == "--eml-dir" else "persona.local.yaml")
    )
    assert calls[0][1]["persona_path"] == expected_persona
    assert capsys.readouterr().out == (
        "Accounts: 2\nUSES: 3 (confirmed: 2, inferred: 1)\nSignals: 1\n"
        "Unknown services: 1\nAccounts per service:\n  google: 2\n"
    )
