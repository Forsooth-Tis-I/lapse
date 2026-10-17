import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import fakeredis
import pytest

from lapse import jobs, worker
from lapse.bot import actions, runtime
from lapse.exec import base, verify
from lapse.signals import tenants


def test_worker_registers_executor_and_detectors(monkeypatch):
    monkeypatch.setenv("HANDLER_MODULES", "lapse.exec.jobs,lapse.signals.jobs")
    monkeypatch.setattr(worker, "HANDLERS", {})
    worker.load_handlers()
    assert set(worker.HANDLERS) == {"execute_change", "run_detectors", "verify_pending"}
    assert asyncio.iscoroutinefunction(worker.HANDLERS["execute_change"])


@pytest.mark.parametrize("fails", [False, True])
def test_worker_awaits_handlers_before_ack_or_retry(monkeypatch, fails):
    monkeypatch.setenv("HANDLER_MODULES", "")
    monkeypatch.setattr(worker, "HANDLERS", {})
    monkeypatch.setattr(worker, "BackgroundScheduler", Mock)
    finished = []
    job = Mock(uid="test_worker", kind="async_test", payload={"value": 7})

    @worker.handler("async_test")
    async def execute(uid, payload):
        await asyncio.sleep(0)
        job.ack.assert_not_called()
        finished.append((uid, payload["value"]))
        if fails:
            raise ValueError("failed after await")

    monkeypatch.setattr(jobs, "consume", lambda: iter([job]))
    worker.run()
    assert finished == [("test_worker", 7)]
    if fails:
        job.retry.assert_called_once_with()
        job.ack.assert_not_called()
    else:
        job.ack.assert_called_once_with()
        job.retry.assert_not_called()


def test_ingest_dispatch_verifies_after_evidence_write(monkeypatch):
    order = []
    monkeypatch.setattr(worker, "HANDLERS", {"ingest_run": lambda uid, payload: order.append("ingest")})
    monkeypatch.setattr(verify, "verify_pending", lambda uid: order.append(("verify", uid)))
    worker.dispatch_job("test_worker", "ingest_run", {})
    assert order == ["ingest", ("verify", "test_worker")]


def test_periodic_checks_include_every_tenant(monkeypatch):
    monkeypatch.setattr(tenants, "tenant_uids", lambda: ["one", "two"])
    queued = []
    monkeypatch.setattr(jobs, "enqueue", lambda *args: queued.append(args))
    worker.enqueue_periodic_jobs()
    assert queued == [
        ("one", "run_detectors", {}),
        ("one", "verify_pending", {}),
        ("two", "run_detectors", {}),
        ("two", "verify_pending", {}),
    ]
    verified = Mock(return_value=["change"])
    monkeypatch.setattr(verify, "verify_pending", verified)
    assert worker.handle_verify_pending("two", {}) == ["change"]
    verified.assert_called_once_with("two")


async def test_executor_events_and_notifications_reach_bot(monkeypatch):
    redis = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(jobs, "client", lambda: redis)
    monkeypatch.setattr(base.db, "user_graph", lambda uid: None)
    monkeypatch.setattr(base.db, "run", lambda *args, **kwargs: SimpleNamespace(rows=[]))
    monkeypatch.setattr(base, "update_change", Mock())
    monkeypatch.setattr(
        runtime,
        "dependency",
        lambda name: SimpleNamespace(chat_for=lambda uid: 7, uid_for=lambda chat: "test_worker"),
    )
    monkeypatch.setattr(
        actions, "get_change", lambda uid, change_id: SimpleNamespace(id=change_id, account_label="X")
    )
    bot = SimpleNamespace(send_message=AsyncMock())
    consumer = runtime.BotRuntime(fakeredis.FakeAsyncRedis(decode_responses=True))
    emitter = base.StepEmitter("test_worker", "change-1")
    with redis.pubsub() as pubsub:
        pubsub.psubscribe("lapse:events:*", "lapse:notify:*")
        pubsub.get_message()
        pubsub.get_message()
        emitter.emit("need_otp", "Enter the SMS code", channel="sms:••7788")
        emitter.emit("need_user", "Open account settings", url="https://x.com/settings/phone")
        delivered = []
        for _ in range(4):
            message = pubsub.get_message()
            assert message is not None
            data = json.loads(message["data"])
            delivered.append(data)
            await consumer.deliver(bot, message["channel"], data)
    assert delivered[0]["data"]["kind"] == "need_otp"
    assert delivered[0]["data"]["change_id"] == "change-1"
    assert delivered[0]["data"]["channel"] == "sms:••7788"
    assert delivered[1] == {"text": "Enter the SMS code", "buttons": []}
    assert consumer.pending[7][0].change_id == "change-1"
    assert consumer.pending[7][0].channel == "sms:••7788"
    keyboard = bot.send_message.call_args.kwargs["reply_markup"]
    assert keyboard.inline_keyboard[0][0].url == "https://x.com/settings/phone"


@pytest.mark.parametrize("url", ["javascript:alert(1)", "file:///private", "https://user@x.com/"])
async def test_bot_rejects_unsafe_executor_links(url):
    with pytest.raises(ValueError, match="HTTPS URL"):
        await runtime.BotRuntime(None).keyboard(
            "test_worker", 7, [{"label": "Settings", "action": "open_url", "payload": {"url": url}}]
        )


@pytest.mark.db
async def test_mcp_approval_token_reaches_real_worker_handler(isolated_graph, monkeypatch):
    from mcp.shared.memory import create_connected_server_and_client_session

    from lapse import approvals
    from lapse.agent.mcp_server import create_server
    from lapse.contracts import Change
    from lapse.graph import db

    redis = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(jobs, "client", lambda: redis)
    monkeypatch.setattr(approvals, "settings", lambda: SimpleNamespace(approval_signing_key="test-only"))
    monkeypatch.setattr(db, "user_graph", lambda uid: isolated_graph)
    monkeypatch.setattr(worker, "HANDLERS", {})
    monkeypatch.setenv("HANDLER_MODULES", "lapse.exec.jobs")
    worker.load_handlers()
    db.run(isolated_graph, "policy_service", {"services": [{"id": "x", "name": "X"}]}, write=True)
    db.run(
        isolated_graph,
        "fixture_accounts",
        {"accounts": [{"id": "account", "service_id": "x", "display": "X"}]},
        write=True,
    )
    db.run(
        isolated_graph,
        "fixture_roots_phone",
        {
            "roots": [
                {"id": "old", "kind": "phone", "label": "Old", "last4": "4321"},
                {"id": "new", "kind": "phone", "label": "New", "last4": "7788"},
            ]
        },
        write=True,
    )
    db.run(isolated_graph, "planner_save_plan", {"props": {"id": "plan"}}, write=True)
    change = Change(
        id="approved-change",
        plan_id="plan",
        order=1,
        account_id="account",
        account_label="X",
        role="login_phone",
        from_root="old",
        to_root="new",
        tier=3,
        requires_old_root=False,
    )
    unrelated = change.model_copy(update={"id": "unrequested-change", "order": 2})
    db.run(
        isolated_graph,
        "planner_save_steps",
        {
            "plan_id": "plan",
            "steps": [item.model_dump(mode="json", exclude_none=True) for item in [change, unrelated]],
        },
        write=True,
    )
    token = approvals.mint("test_worker", [change.id, unrelated.id])
    async with create_connected_server_and_client_session(create_server()) as client:
        response = await client.call_tool(
            "execute_change",
            {"change_id": change.id, "approval_token": token},
            meta={"lapse/uid": "test_worker"},
        )
        result = json.loads(response.content[0].text)
        assert result["change_id"] == change.id
        assert result["job_id"]
        stream = jobs.consume()
        try:
            queued = next(stream)
            outcome = await asyncio.to_thread(worker.dispatch_job, queued.uid, queued.kind, queued.payload)
            queued.ack()
        finally:
            stream.close()
        assert outcome == {"change_id": change.id, "status": "awaiting_user"}
        assert (
            db.run(isolated_graph, "planner_get_change", {"change_id": unrelated.id}).rows[0]["change"][
                "status"
            ]
            == "proposed"
        )
        replay = await client.call_tool(
            "execute_change",
            {"change_id": change.id, "approval_token": token},
            meta={"lapse/uid": "test_worker"},
        )
        assert json.loads(replay.content[0].text)["outcome"] == "error"
        assert redis.xlen(jobs.STREAM) == 1
