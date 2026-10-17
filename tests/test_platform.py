import asyncio
import json
import time
from threading import Thread
from types import SimpleNamespace
from unittest.mock import Mock

import fakeredis
import pytest

from lapse import approvals, events, jobs, otp, telegram_link, worker
from lapse.notify import notify


@pytest.fixture
def redis(monkeypatch):
    server = fakeredis.FakeServer()
    connection = fakeredis.FakeRedis(server=server, decode_responses=True)
    monkeypatch.setattr(jobs, "client", lambda: connection)
    monkeypatch.setattr(events, "async_client", lambda: fakeredis.FakeAsyncRedis(server=server))
    monkeypatch.setattr(approvals, "settings", lambda: SimpleNamespace(approval_signing_key="test-key"))
    return connection


def test_publish_graph_event(redis):
    with redis.pubsub() as pubsub:
        pubsub.subscribe("lapse:events:u1")
        pubsub.get_message()
        events.publish("u1", "graph", {"changed": ["account"]})
        message = json.loads(pubsub.get_message()["data"])
        assert message["uid"] == "u1"
        assert message["type"] == "graph"
        assert message["data"] == {"changed": ["account"]}
        assert message["at"].endswith("Z")


async def test_subscribe_and_cleanup(redis):
    stream = events.subscribe("u1")
    pending = asyncio.create_task(anext(stream))
    for _ in range(100):
        if redis.pubsub_numsub("lapse:events:u1")[0][1]:
            break
        await asyncio.sleep(0.001)
    events.publish("other", "graph", {"ignored": True})
    events.publish("u1", "plan", {"id": "plan1"})
    event = await asyncio.wait_for(pending, timeout=1)
    assert event.type == "plan"
    assert event.uid == "u1"
    assert event.data == {"id": "plan1"}
    await stream.aclose()
    assert redis.pubsub_numsub("lapse:events:u1") == [("lapse:events:u1", 0)]


def test_notify(redis):
    buttons = [{"label": "Approve", "action": "approve_changes", "payload": {"change_ids": ["c1"]}}]
    with redis.pubsub() as pubsub:
        pubsub.subscribe("lapse:notify:u1")
        pubsub.get_message()
        notify("u1", "Ready", buttons)
        assert json.loads(pubsub.get_message()["data"]) == {"text": "Ready", "buttons": buttons}
        notify("u1", "Done")
        assert json.loads(pubsub.get_message()["data"]) == {"text": "Done", "buttons": []}


def test_approval_tenant_tamper_single_use_and_ttl(redis):
    token = approvals.mint("u1", ["c1", "c2"])
    nonce, signature = token.split(".")
    assert redis.ttl(f"lapse:approval:{nonce}") == 900
    with pytest.raises(ValueError, match="Invalid"):
        approvals.consume("u2", token)
    with pytest.raises(ValueError, match="Invalid"):
        approvals.consume("u1", f"{nonce}.{'0' if signature[0] != '0' else '1'}{signature[1:]}")
    assert approvals.consume("u1", token) == ["c1", "c2"]
    with pytest.raises(ValueError, match="already used"):
        approvals.consume("u1", token)


def test_expired_approval_and_missing_key(redis, monkeypatch):
    token = approvals.mint("u1", ["c1"])
    redis.expire(f"lapse:approval:{token.split('.')[0]}", 0)
    with pytest.raises(ValueError, match="expired"):
        approvals.consume("u1", token)
    monkeypatch.setattr(approvals, "settings", lambda: SimpleNamespace(approval_signing_key=""))
    with pytest.raises(RuntimeError, match="APPROVAL_SIGNING_KEY"):
        approvals.mint("u1", ["c1"])


def test_otp_ttl_tenant_and_one_time_delivery(redis):
    otp.submit("u1", "c1", "012345")
    assert redis.ttl("lapse:otp:u1:c1") == 300
    assert otp.wait("other", "c1", timeout_s=0) is None
    assert otp.wait("u1", "c1", timeout_s=0) == "012345"
    assert otp.wait("u1", "c1", timeout_s=0) is None


def test_otp_waits_for_arrival(redis, monkeypatch):
    monkeypatch.setattr(otp.time, "sleep", lambda _: otp.submit("u1", "c1", "345678"))
    assert otp.wait("u1", "c1", timeout_s=1) == "345678"


def test_jobs_enqueue_consume_ack(redis):
    job_id = jobs.enqueue("u1", "execute_change", {"change_id": "c1"})
    consumer = jobs.consume()
    job = next(consumer)
    assert job.id == job_id
    assert job.uid == "u1"
    assert job.kind == "execute_change"
    assert job.payload == {"change_id": "c1"}
    assert job.attempts == 1
    assert redis.xpending(jobs.STREAM, "workers")["pending"] == 1
    job.ack()
    assert redis.xpending(jobs.STREAM, "workers")["pending"] == 0
    consumer.close()


def test_jobs_bounded_retry(redis):
    jobs.enqueue("u1", "ingest_run", {"inbox": "primary"})
    consumer = jobs.consume()
    first = next(consumer)
    retry_id = first.retry()
    assert redis.xpending(jobs.STREAM, "workers")["pending"] == 0
    second = next(consumer)
    assert second.id == retry_id
    assert second.attempts == 2
    assert second.payload == {"inbox": "primary"}
    second.retry()
    third = next(consumer)
    assert third.attempts == 3
    assert third.retry() is None
    assert redis.xlen("lapse:jobs:failed") == 1
    assert redis.xpending(jobs.STREAM, "workers")["pending"] == 0
    consumer.close()


def test_jobs_recover_abandoned_pending(redis, monkeypatch):
    job_id = jobs.enqueue("u1", "run_detectors", {})
    abandoned = jobs.consume()
    assert next(abandoned).id == job_id
    abandoned.close()
    monkeypatch.setattr(jobs, "RECLAIM_AFTER_MS", 0)
    replacement = jobs.consume()
    recovered = next(replacement)
    assert recovered.id == job_id
    recovered.ack()
    assert redis.xpending(jobs.STREAM, "workers")["pending"] == 0
    replacement.close()


def test_telegram_single_use_and_binding(redis):
    code = telegram_link.new_link_code("u1")
    assert redis.ttl(f"lapse:tglink:{code}") == 3600
    assert telegram_link.chat_for("u1") is None
    assert telegram_link.bind(code, 123) == "u1"
    assert telegram_link.chat_for("u1") == 123
    assert telegram_link.uid_for(123) == "u1"
    with pytest.raises(ValueError, match="already used"):
        telegram_link.bind(code, 456)
    assert telegram_link.chat_for("u1") == 123


def test_telegram_rebinding_removes_old_links(redis):
    telegram_link.bind(telegram_link.new_link_code("u1"), 123)
    telegram_link.bind(telegram_link.new_link_code("u2"), 456)
    telegram_link.bind(telegram_link.new_link_code("u1"), 456)
    assert telegram_link.chat_for("u1") == 456
    assert telegram_link.uid_for(456) == "u1"
    assert telegram_link.uid_for(123) is None
    assert telegram_link.chat_for("u2") is None


def test_telegram_expired_link(redis):
    code = telegram_link.new_link_code("u1")
    redis.expire(f"lapse:tglink:{code}", 0)
    with pytest.raises(ValueError, match="expired"):
        telegram_link.bind(code, 123)


def test_worker_registry_dispatch_scheduler_and_missing_modules(redis, monkeypatch, caplog):
    monkeypatch.setattr(worker, "HANDLERS", {})
    monkeypatch.setattr(worker, "settings", lambda: SimpleNamespace(uid="u1"))
    monkeypatch.setenv("HANDLER_MODULES", "lapse.exec.jobs, lapse.ingest.jobs")
    executed = []

    @worker.handler("execute_change")
    def execute(uid, payload):
        executed.append((uid, payload))

    def missing(name):
        raise ModuleNotFoundError(name=name)

    monkeypatch.setattr(worker.importlib, "import_module", missing)
    scheduler = Mock()
    monkeypatch.setattr(worker, "BackgroundScheduler", lambda: scheduler)
    good = Mock(uid="u1", kind="execute_change", payload={"change_id": "c1"})
    bad = Mock(uid="u1", kind="unregistered", payload={})
    monkeypatch.setattr(jobs, "consume", lambda: iter([good, bad]))
    worker.run()
    assert executed == [("u1", {"change_id": "c1"})]
    good.ack.assert_called_once_with()
    bad.retry.assert_called_once_with()
    scheduler.add_job.assert_called_once_with(
        jobs.enqueue, "interval", minutes=5, args=["u1", "run_detectors", {}]
    )
    scheduler.start.assert_called_once_with()
    scheduler.shutdown.assert_called_once_with()
    assert "lapse.exec.jobs is not installed" in caplog.text


def test_worker_does_not_hide_broken_dependency(redis, monkeypatch):
    monkeypatch.setenv("HANDLER_MODULES", "lapse.ingest.jobs")

    def broken(name):
        raise ModuleNotFoundError(name="broken_dependency")

    monkeypatch.setattr(worker.importlib, "import_module", broken)
    with pytest.raises(ModuleNotFoundError):
        worker.run()


@pytest.mark.parametrize("fails", [False, True])
def test_worker_renews_active_job_and_stops_heartbeat(redis, monkeypatch, fails):
    monkeypatch.setattr(jobs, "RECLAIM_AFTER_MS", 240)
    monkeypatch.setenv("HANDLER_MODULES", "")
    monkeypatch.setattr(worker, "HANDLERS", {})
    monkeypatch.setattr(worker, "BackgroundScheduler", Mock)
    job_id = jobs.enqueue("u1", "execute_change", {"change_id": "c1"})
    stream = jobs.consume()
    active = next(stream)
    competing_consume = jobs.consume
    threads = []
    observed = {}

    def create_thread(**kwargs):
        thread = Thread(**kwargs)
        threads.append(thread)
        return thread

    monkeypatch.setattr(worker, "Thread", create_thread)
    monkeypatch.setattr(jobs, "consume", lambda: iter([active]))

    @worker.handler("execute_change")
    def execute(uid, payload):
        time.sleep(0.65)
        pending = redis.xpending_range(jobs.STREAM, "workers", job_id, job_id, 1)[0]
        observed["idle_ms"] = pending["time_since_delivered"]
        next_id = jobs.enqueue("u2", "run_detectors", {})
        competitor = competing_consume()
        other = next(competitor)
        observed["expected_id"] = next_id
        observed["other_id"] = other.id
        other.ack()
        competitor.close()
        if fails:
            raise ValueError("handler failed")

    worker.run()
    assert observed["idle_ms"] < 240
    assert observed["other_id"] == observed["expected_id"]
    assert len(threads) == 1
    assert not threads[0].is_alive()
    assert redis.xpending(jobs.STREAM, "workers")["pending"] == 0
    assert redis.xlen(jobs.STREAM) == (3 if fails else 2)
    stream.close()


def test_lease_renewal_never_takes_back_a_reassigned_job(redis):
    job_id = jobs.enqueue("u1", "execute_change", {})
    stream = jobs.consume()
    job = next(stream)
    assert job.renew_lease()
    redis.xclaim(jobs.STREAM, "workers", "replacement", 0, [job_id])
    assert not job.renew_lease()
    pending = redis.xpending_range(jobs.STREAM, "workers", job_id, job_id, 1)[0]
    assert pending["consumer"] == "replacement"
    stream.close()
