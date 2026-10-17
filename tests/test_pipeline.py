from contextlib import contextmanager
from pathlib import Path

import pytest

from lapse.ingest import pipeline
from lapse.ingest.pipeline import PrefilterStats, iter_events

CORPUS = Path(__file__).parent / "fixtures/emails"


def test_corpus_end_to_end(tmp_path):
    stats = PrefilterStats()
    events = list(
        iter_events(
            ["email_primary", "email_college"],
            live=False,
            use_llm=False,
            eml_dir=CORPUS,
            stats=stats,
            cache_path=tmp_path / "cache.json",
        )
    )
    assert stats.fetched == 30
    assert stats.kept == 26
    assert stats.dropped_by_reason == {"no_service_or_keyword": 4}
    assert len(events) == 26
    by_id = {event.msg_id: event for event in events}
    college = by_id["<synthetic-18@example.com>"]
    assert college.inbox == "email_college"
    assert college.account_identifier == "demo@example.edu"
    assert college.event == "deactivation_notice"
    assert str(college.deadline) == "2026-11-15"
    phone = by_id["<synthetic-02@example.com>"]
    assert phone.service_id == "google"
    assert phone.contact_change.old_last4 == "4321"
    assert phone.contact_change.new_last4 == "7788"
    assert by_id["<synthetic-01@example.com>"].device == "Pixel 9"
    assert by_id["<synthetic-16@example.com>"].phone_last4 == ["21"]
    assert by_id["<synthetic-09@example.com>"].event == "otp_email"
    assert by_id["<synthetic-10@example.com>"].event == "otp_email"
    assert all(len(event.snippet) <= 300 for event in events)
    output = "\n".join(event.model_dump_json() for event in events)
    assert "91827" not in output
    assert "maple-river-forest" not in output
    assert not (tmp_path / "cache.json").exists()


@pytest.mark.parametrize("count", [1, 20, 21])
def test_live_checkpoint_waits_for_last_event(raw, monkeypatch, tmp_path, count):
    committed = []

    @contextmanager
    def scan(inbox, **kwargs):
        assert kwargs["uid"] == "tenant"
        yield iter([raw("Welcome", msg_id=f"<{i}@example.com>") for i in range(count)])
        committed.append(inbox)

    monkeypatch.setattr(pipeline, "fetch_emails", scan)
    stream = iter_events(["email_primary"], uid="tenant", use_llm=False, cache_path=tmp_path / "c")
    for _ in range(count):
        next(stream)
        assert committed == []
    with pytest.raises(StopIteration):
        next(stream)
    assert committed == ["email_primary"]
    committed.clear()
    stream = iter_events(["email_primary"], uid="tenant", use_llm=False, cache_path=tmp_path / "c")
    next(stream)
    stream.close()
    assert committed == []


def test_dry_run_outputs_jsonl_and_stats(monkeypatch, capsys):
    import json

    from scripts.ingest_dry_run import main

    monkeypatch.setattr("sys.argv", ["ingest_dry_run.py", "--no-llm", "--eml-dir", str(CORPUS)])
    main()
    output = capsys.readouterr()
    assert len([json.loads(line) for line in output.out.splitlines()]) == 26
    assert json.loads(output.err) == {
        "fetched": 30,
        "kept": 26,
        "dropped_by_reason": {"no_service_or_keyword": 4},
    }
