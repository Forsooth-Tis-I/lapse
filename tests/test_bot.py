import asyncio
import json
import sys
from datetime import UTC, date, datetime
from html import unescape
from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from telegram.error import BadRequest

from lapse.bot import actions, cards, main
from lapse.bot.runtime import BotRuntime, PendingOTP
from lapse.contracts import Change, Plan, Reached, Root, ScenarioResult, Signal


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.ttls = {}

    async def set(self, key, value, *, ex):
        self.values[key] = value
        self.ttls[key] = ex

    async def getdel(self, key):
        return self.values.pop(key, None)


class FakeMessage:
    def __init__(self, text="hello"):
        self.text = text
        self.message_id = 42
        self.edits = []
        self.replies = []

    async def edit_text(self, **kwargs):
        self.edits.append(kwargs)

    async def reply_text(self, text):
        self.replies.append(text)


class FakeBot:
    def __init__(self):
        self.sent = []
        self.typing = []
        self.deleted = []

    async def send_message(self, **kwargs):
        message = FakeMessage(kwargs["text"])
        self.sent.append((kwargs, message))
        return message

    async def send_chat_action(self, **kwargs):
        self.typing.append(kwargs)

    async def delete_message(self, **kwargs):
        self.deleted.append(kwargs)


@pytest.fixture
def harness(monkeypatch):
    modules = {
        "telegram_link": SimpleNamespace(
            uid_for=Mock(return_value="u"),
            chat_for=Mock(return_value=7),
            bind=Mock(return_value="u"),
            new_link_code=Mock(return_value="link-code"),
        ),
        "agent.agent": SimpleNamespace(
            respond=AsyncMock(return_value={"text": "Hello", "buttons": [], "tool_calls": []})
        ),
        "approvals": SimpleNamespace(mint=Mock(return_value="signed"), consume=Mock(return_value=["c1"])),
        "jobs": SimpleNamespace(enqueue=Mock(return_value="job1")),
        "otp": SimpleNamespace(submit=Mock()),
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, f"lapse.{name}", module)
    bot = FakeBot()
    message = FakeMessage()
    query = SimpleNamespace(message=message, data=None, answer=AsyncMock(), edit_message_text=AsyncMock())
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=7, type="private"), effective_message=message, callback_query=query
    )
    context = SimpleNamespace(bot=bot, args=[])
    runtime = BotRuntime(FakeRedis(), slow_after=0.001)
    return SimpleNamespace(runtime=runtime, update=update, context=context, bot=bot, modules=modules)


@pytest.fixture
def plan():
    return Plan(
        id="plan1",
        kind="takeover",
        old_root="old",
        new_root="new",
        deadline=date(2026, 10, 31),
        feasible=True,
        exposure_before=8,
        exposure_after=0,
        created_at=datetime.now(UTC),
        steps=[
            Change(
                id=f"c{i}",
                plan_id="plan1",
                order=i,
                account_id=f"a{i}",
                account_label=f"Account <{i}>",
                role="recovery_phone",
                from_root="old",
                to_root="new",
                tier=i,
                requires_old_root=True,
                due=date(2026, 10, 30),
            )
            for i in range(1, 5)
        ],
    )


@pytest.fixture
def scenario():
    return ScenarioResult(
        id="scenario1",
        kind="takeover",
        root_ids=["old"],
        actor="stranger",
        rounds=3,
        affected_accounts=[
            Reached(node_id=f"a{i}", label=f"Account <{i}>", node_type="Account", round=i)
            for i in range(1, 4)
        ],
        direct_accounts=["a1"],
        unknown_accounts=["unknown"],
        total_accounts=4,
        ms=1,
    )


def last_text(harness):
    return harness.bot.sent[-1][0]["text"]


async def press(h, action, payload):
    keyboard = await h.runtime.keyboard("u", 7, [{"label": "Do it", "action": action, "payload": payload}])
    h.update.callback_query.data = keyboard.inline_keyboard[0][0].callback_data
    await h.runtime.callback(h.update, h.context)


async def test_start_binds_code(harness):
    h = harness
    h.context.args = ["one-time-code"]
    await h.runtime.start(h.update, h.context)
    h.modules["telegram_link"].bind.assert_called_once_with("one-time-code", 7)
    assert last_text(h).startswith("Connected.")


async def test_start_requires_onboarding_without_explicit_default(harness):
    h = harness
    h.modules["telegram_link"].uid_for.return_value = None
    await h.runtime.start(h.update, h.context)
    assert "http://localhost:5173/onboarding" in last_text(h)
    assert "&lt;code&gt;" in last_text(h)
    h.modules["telegram_link"].bind.assert_not_called()


async def test_default_binding_uses_one_time_link_path(harness):
    h = harness
    h.modules["telegram_link"].uid_for.return_value = None
    h.runtime.default_uid = "explicit-user"
    await h.runtime.start(h.update, h.context)
    h.modules["telegram_link"].new_link_code.assert_called_once_with("explicit-user")
    h.modules["telegram_link"].bind.assert_called_once_with("link-code", 7)


async def test_invalid_link_and_group_do_not_bind(harness):
    h = harness
    h.context.args = ["bad"]
    h.modules["telegram_link"].bind.side_effect = ValueError("sensitive")
    await h.runtime.start(h.update, h.context)
    assert "invalid or expired" in last_text(h)
    assert "sensitive" not in last_text(h)
    h.modules["telegram_link"].bind.reset_mock()
    h.update.effective_chat.type = "group"
    await h.runtime.start(h.update, h.context)
    h.modules["telegram_link"].bind.assert_not_called()


async def test_help(harness):
    h = harness
    await h.runtime.help(h.update, h.context)
    assert all(
        command in h.update.effective_message.replies[0]
        for command in ("/start", "/status", "/risk", "/help")
    )


async def test_status_roots_open_plans_signals_and_deadlines(harness, monkeypatch, plan):
    from lapse.bot.runtime import planner, views

    h = harness
    monkeypatch.setattr(
        views,
        "list_roots",
        lambda uid: [
            Root(id="old", kind="phone", label="Old & phone", status="retiring", drop_at=date(2026, 10, 31))
        ],
    )
    monkeypatch.setattr(planner, "list_plans", lambda uid: [plan])
    monkeypatch.setattr(
        actions,
        "list_signals",
        lambda uid: [
            Signal(
                id="s",
                kind="stale_root",
                root_id="old",
                at=datetime.now(UTC),
                title="Check <phone>",
                detail="",
                deadline=date(2026, 10, 30),
            )
        ],
    )
    await h.runtime.status(h.update, h.context)
    assert "Old &amp; phone" in last_text(h)
    assert "4 steps left · due 2026-10-31" in last_text(h)
    assert "Check &lt;phone&gt; · due 2026-10-30" in last_text(h)


async def test_unlinked_status_never_reads_graph(harness, monkeypatch):
    from lapse.bot.runtime import views

    h = harness
    h.modules["telegram_link"].uid_for.return_value = None
    roots = Mock()
    monkeypatch.setattr(views, "list_roots", roots)
    await h.runtime.status(h.update, h.context)
    roots.assert_not_called()
    assert "onboarding" in last_text(h)


async def test_risk_selects_kind_for_retiring_roots(harness, monkeypatch, scenario):
    from lapse.bot.runtime import scenarios, views

    h = harness
    roots = [
        Root(id="old", kind="phone", label="Phone", status="retiring"),
        Root(id="college", kind="email", label="College", status="closing"),
        Root(id="current", kind="phone", label="Current"),
    ]
    monkeypatch.setattr(views, "list_roots", lambda uid: roots)
    run = Mock(return_value=scenario)
    monkeypatch.setattr(scenarios, "run_scenario", run)
    await h.runtime.risk(h.update, h.context)
    assert [(call.args[1].kind, call.args[1].root_ids) for call in run.call_args_list] == [
        ("takeover", ["old"]),
        ("lockout", ["college"]),
    ]
    assert "Directly: 1 accounts · Through other accounts: 2 more · Unknown: 1" in last_text(h)
    assert "unknown, not safe" in last_text(h)


async def test_buttons_short_storage_bound_to_user_and_chat(harness):
    h = harness
    buttons = [
        {"label": "Web", "action": "open_web", "payload": {"path": "/graph?scenario=s"}},
        {"label": "Plan", "action": "plan_root", "payload": {"root_id": "x" * 300}},
    ]
    keyboard = await h.runtime.keyboard("u", 7, buttons)
    assert keyboard.inline_keyboard[0][0].url == "http://localhost:5173/graph?scenario=s"
    callback = keyboard.inline_keyboard[1][0].callback_data
    assert len(callback.encode()) <= 64
    key = f"lapse:bot:callback:u:7:{callback}"
    assert json.loads(h.runtime.redis.values[key]) == {
        "action": "plan_root",
        "payload": {"root_id": "x" * 300},
    }
    assert h.runtime.redis.ttls[key] == 900
    h.update.callback_query.data = callback
    h.modules["telegram_link"].uid_for.return_value = "another-user"
    await h.runtime.callback(h.update, h.context)
    assert key in h.runtime.redis.values
    assert "expired" in h.update.callback_query.edit_message_text.call_args.args[0]


@pytest.mark.parametrize("path", ["https://evil.example", "//evil.example", "/\\evil", "relative"])
async def test_web_button_cannot_leave_configured_host(harness, path):
    with pytest.raises(ValueError):
        await harness.runtime.keyboard(
            "u", 7, [{"label": "bad", "action": "open_web", "payload": {"path": path}}]
        )


async def test_approval_mints_on_click_consumes_once_then_updates_and_enqueues(harness, monkeypatch, plan):
    from lapse.bot.runtime import planner

    h = harness
    sequence = []
    h.modules["approvals"].mint.side_effect = lambda uid, ids: sequence.append(("mint", uid, ids)) or "signed"
    h.modules["approvals"].consume.side_effect = lambda uid, token: (
        sequence.append(("consume", uid, token)) or ["c1"]
    )
    monkeypatch.setattr(
        planner,
        "update_change",
        lambda uid, cid, **kwargs: sequence.append(("update", uid, cid, kwargs["status"])) or plan.steps[0],
    )
    h.modules["jobs"].enqueue.side_effect = lambda *args: sequence.append(("enqueue", *args))
    keyboard = await h.runtime.keyboard(
        "u", 7, [{"label": "Approve", "action": "approve_changes", "payload": {"change_ids": ["c1"]}}]
    )
    assert sequence == []
    h.update.callback_query.data = keyboard.inline_keyboard[0][0].callback_data
    await h.runtime.callback(h.update, h.context)
    assert sequence == [
        ("mint", "u", ["c1"]),
        ("consume", "u", "signed"),
        ("update", "u", "c1", "approved"),
        ("enqueue", "u", "execute_change", {"change_id": "c1"}),
    ]
    assert "Account &lt;1&gt; · T1 auto" in h.update.effective_message.edits[0]["text"]
    await h.runtime.callback(h.update, h.context)
    assert len(sequence) == 4


async def test_invalid_approval_token_never_queues(harness):
    h = harness
    h.modules["approvals"].consume.side_effect = ValueError("expired")
    with pytest.raises(ValueError):
        await press(h, "approve_changes", {"token": "bad"})
    h.modules["jobs"].enqueue.assert_not_called()


async def test_plan_callback_card_and_approval_excludes_tier_four(harness, monkeypatch, plan, scenario):
    from lapse.bot.runtime import planner, scenarios

    h = harness
    plan_for_root = Mock(return_value=plan)
    monkeypatch.setattr(planner, "plan_for_root", plan_for_root)
    monkeypatch.setattr(scenarios, "run_scenario", lambda *args: scenario)
    await press(h, "plan_root", {"root_id": "old"})
    plan_for_root.assert_called_once_with("u", "old", None)
    text = h.update.effective_message.edits[0]["text"]
    assert text.startswith("Directly:")
    assert all(tier in text for tier in ("T1 auto", "T2 your code", "T3 you do it"))
    assert "due 2026-10-30" in text
    assert "+ 1 more steps" in text
    records = [json.loads(value) for value in h.runtime.redis.values.values()]
    assert records == [{"action": "approve_changes", "payload": {"change_ids": ["c1", "c2", "c3"]}}]


@pytest.mark.parametrize("value", [True, False])
async def test_confirm_use_callback(harness, monkeypatch, value):
    confirm = Mock()
    monkeypatch.setattr(actions, "confirm_use", confirm)
    await press(
        harness, "confirm_use", {"account_id": "a", "root_id": "r", "role": "sms_2fa", "value": value}
    )
    confirm.assert_called_once_with("u", "a", "r", "sms_2fa", value)


async def test_dismiss_callback(harness, monkeypatch):
    dismiss = Mock()
    monkeypatch.setattr(actions, "dismiss_signal", dismiss)
    await press(harness, "dismiss_signal", {"signal_id": "s"})
    dismiss.assert_called_once_with("u", "s")
    assert harness.update.effective_message.edits[0]["text"] == "Signal dismissed."


async def test_slow_agent_typing_and_edits_working_message(harness):
    h = harness
    release = asyncio.Event()

    async def respond(uid, text, *, channel):
        assert (uid, text, channel) == ("u", "hello", "telegram")
        await release.wait()
        return SimpleNamespace(text='<b>literal</b> & "quoted"', buttons=[], tool_calls=[])

    h.modules["agent.agent"].respond = respond
    task = asyncio.create_task(h.runtime.text(h.update, h.context))
    for _ in range(100):
        if h.bot.sent:
            break
        await asyncio.sleep(0.001)
    assert last_text(h) == "Working on it…"
    release.set()
    await task
    assert len(h.bot.sent) == 1
    assert h.bot.sent[0][1].edits[0]["text"] == "&lt;b&gt;literal&lt;/b&gt; &amp; &quot;quoted&quot;"
    assert h.bot.sent[0][1].edits[0]["parse_mode"] == "HTML"
    assert h.bot.typing[0] == {"chat_id": 7, "action": "typing"}


async def test_fast_sync_agent_reply_and_buttons(harness):
    h = harness
    h.runtime.slow_after = 1
    h.modules["agent.agent"].respond = Mock(
        return_value={
            "text": "Fast & done",
            "buttons": [{"label": "Open", "action": "open_web", "payload": {"path": "/graph"}}],
            "tool_calls": [],
        }
    )
    await h.runtime.text(h.update, h.context)
    assert last_text(h) == "Fast &amp; done"
    assert len(h.bot.sent) == 1
    assert h.bot.sent[0][0]["reply_markup"].inline_keyboard[0][0].url.endswith("/graph")


async def test_long_reply_splits_without_breaking_html(harness):
    h = harness
    await h.runtime.send(h.bot, "u", 7, "<&😀" * 1500)
    assert len(h.bot.sent) == 3
    assert all(len(unescape(message.text).encode("utf-16-le")) <= 8192 for _, message in h.bot.sent)
    assert "".join(message.text for _, message in h.bot.sent) == "&lt;&amp;😀" * 1500


def event(change_id="c1", kind="need_otp", uid="u"):
    return {
        "type": "exec",
        "uid": uid,
        "at": datetime.now(UTC).isoformat(),
        "data": {
            "kind": kind,
            "change_id": change_id,
            "channel": "sms:••7788",
            "message": "Code required",
            "at": datetime.now(UTC).isoformat(),
        },
    }


async def test_need_otp_event_then_relay_and_deletion(harness, monkeypatch, plan, caplog):
    h = harness
    monkeypatch.setattr(actions, "get_change", lambda *args: plan.steps[0])
    await h.runtime.deliver(h.bot, "lapse:events:u", event())
    assert last_text(h) == "Account &lt;1&gt; sent a code to sms:••7788. Reply with it (5 min)."
    assert h.runtime.pending[7][0].change_id == "c1"
    h.update.effective_message.text = "123456"
    await h.runtime.text(h.update, h.context)
    h.modules["otp"].submit.assert_called_once_with("u", "c1", "123456")
    assert h.bot.deleted == [{"chat_id": 7, "message_id": 42}]
    assert last_text(h) == "Code passed to the agent"
    h.modules["agent.agent"].respond.assert_not_called()
    assert not h.runtime.pending[7]
    assert "123456" not in json.dumps(h.runtime.redis.values) + repr(h.bot.sent) + caplog.text


@pytest.mark.parametrize("state", ["expired", "other-user"])
async def test_unmatched_code_never_goes_to_agent(harness, state):
    h = harness
    if state != "absent":
        h.runtime.pending[7].append(
            PendingOTP(
                "other" if state == "other-user" else "u",
                "c",
                "service",
                "sms",
                monotonic() + (-1 if state == "expired" else 100),
            )
        )
    h.update.effective_message.text = "1234"
    await h.runtime.text(h.update, h.context)
    h.modules["otp"].submit.assert_not_called()
    h.modules["agent.agent"].respond.assert_not_called()
    assert len(h.bot.deleted) == 1
    assert "no active code request" in last_text(h)


async def test_numeric_reply_without_otp_request_reaches_agent(harness):
    h = harness
    h.update.effective_message.text = "2026"
    await h.runtime.text(h.update, h.context)
    h.modules["agent.agent"].respond.assert_awaited_once_with("u", "2026", channel="telegram")
    h.modules["otp"].submit.assert_not_called()
    assert h.bot.deleted == []


@pytest.mark.parametrize("new_change", ["c1", "c2"])
async def test_expired_otp_does_not_block_next_prompt(harness, monkeypatch, plan, new_change):
    h = harness
    h.runtime.pending[7].append(PendingOTP("u", "c1", "Old service", "sms", monotonic() - 1))
    change = next(step for step in plan.steps if step.id == new_change)
    monkeypatch.setattr(actions, "get_change", lambda *args: change)
    await h.runtime.deliver(h.bot, "lapse:events:u", event(new_change))
    assert len(h.runtime.pending[7]) == 1
    assert h.runtime.pending[7][0].change_id == new_change
    assert "sent a code" in last_text(h)


async def test_delete_failure_still_confirms_submission(harness):
    h = harness
    h.runtime.pending[7].append(PendingOTP("u", "c1", "Service", "sms", monotonic() + 300))
    h.bot.delete_message = AsyncMock(side_effect=BadRequest("cannot delete"))
    h.update.effective_message.text = "987654"
    await h.runtime.text(h.update, h.context)
    assert "Please delete it" in h.bot.sent[0][0]["text"]
    assert last_text(h) == "Code passed to the agent"


async def test_otp_submit_failure_deletes_message_and_preserves_request(harness, caplog):
    h = harness
    h.runtime.pending[7].append(PendingOTP("u", "c1", "Service", "sms", monotonic() + 300))
    h.modules["otp"].submit.side_effect = RedisConnectionError("unavailable")
    h.update.effective_message.text = "987654"
    with pytest.raises(RedisConnectionError):
        await h.runtime.text(h.update, h.context)
    assert h.bot.deleted == [{"chat_id": 7, "message_id": 42}]
    assert h.runtime.pending[7][0].change_id == "c1"
    assert "987654" not in caplog.text
    h.modules["otp"].submit.side_effect = None
    await h.runtime.text(h.update, h.context)
    h.modules["agent.agent"].respond.assert_not_called()
    assert last_text(h) == "Code passed to the agent"


async def test_duplicate_code_during_submission_never_reaches_agent(harness):
    h = harness
    h.modules["telegram_link"].uid_for = AsyncMock(return_value="u")
    h.runtime.pending[7].append(PendingOTP("u", "c1", "Service", "sms", monotonic() + 300))
    entered, release = asyncio.Event(), asyncio.Event()

    async def submit(*args):
        entered.set()
        await release.wait()

    h.modules["otp"].submit = AsyncMock(side_effect=submit)
    h.update.effective_message.text = "123456"
    first = asyncio.create_task(h.runtime.text(h.update, h.context))
    await entered.wait()
    second = asyncio.create_task(h.runtime.text(h.update, h.context))
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(first, second)
    h.modules["otp"].submit.assert_awaited_once_with("u", "c1", "123456")
    h.modules["agent.agent"].respond.assert_not_called()
    assert len(h.bot.deleted) == 2


async def test_simultaneous_otp_requests_do_not_overwrite_each_other(harness, monkeypatch, plan):
    h = harness
    monkeypatch.setattr(
        actions, "get_change", lambda uid, cid: next(step for step in plan.steps if step.id == cid)
    )
    await h.runtime.deliver(h.bot, "lapse:events:u", event("c1"))
    await h.runtime.deliver(h.bot, "lapse:events:u", event("c2"))
    assert len(h.bot.sent) == 1
    h.update.effective_message.text = "111111"
    await h.runtime.text(h.update, h.context)
    assert h.runtime.pending[7][0].change_id == "c2"
    assert last_text(h).startswith("Account &lt;2&gt; sent a code")


async def test_notify_delivery_buttons_and_unknown_binding(harness):
    h = harness
    data = {
        "text": "New <risk>",
        "buttons": [{"label": "Plan", "action": "plan_root", "payload": {"root_id": "old"}}],
    }
    await h.runtime.deliver(h.bot, "lapse:notify:u", data)
    assert last_text(h) == "New &lt;risk&gt;"
    assert h.bot.sent[0][0]["reply_markup"]
    h.modules["telegram_link"].chat_for.return_value = None
    await h.runtime.deliver(h.bot, "lapse:notify:unknown", data)
    assert len(h.bot.sent) == 1


async def test_event_uid_mismatch_is_ignored(harness, monkeypatch):
    get = Mock()
    monkeypatch.setattr(actions, "get_change", get)
    await harness.runtime.deliver(harness.bot, "lapse:events:u", event(uid="other"))
    get.assert_not_called()
    assert not harness.bot.sent


async def test_listener_subscribes_routes_and_closes(harness):
    h = harness
    stopped = asyncio.Event()

    class Pubsub:
        psubscribe = AsyncMock()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            stopped.set()

        async def listen(self):
            yield {"type": "psubscribe"}
            yield {"type": "pmessage", "channel": "lapse:notify:u", "data": "not json"}
            yield {"type": "pmessage", "channel": "lapse:notify:u", "data": json.dumps({"text": "Delivered"})}
            await asyncio.Event().wait()

    pubsub = Pubsub()
    h.runtime.redis.pubsub = lambda: pubsub
    h.runtime.redis.aclose = AsyncMock()
    app = SimpleNamespace(bot=h.bot)
    await h.runtime.startup(app)
    for _ in range(100):
        if h.bot.sent:
            break
        await asyncio.sleep(0.001)
    assert last_text(h) == "Delivered"
    await h.runtime.shutdown(app)
    assert stopped.is_set()
    pubsub.psubscribe.assert_awaited_once_with("lapse:notify:*", "lapse:events:*")
    h.runtime.redis.aclose.assert_awaited_once()


def test_config_check_and_missing_token(monkeypatch, capsys):
    monkeypatch.setattr(main, "settings", lambda: SimpleNamespace(telegram_bot_token=""))
    monkeypatch.setattr(sys, "argv", ["bot", "--check"])
    with pytest.raises(SystemExit) as exc:
        main.run()
    assert exc.value.code == 2
    assert "TELEGRAM_BOT_TOKEN is required" in capsys.readouterr().err
    monkeypatch.setattr(main, "settings", lambda: SimpleNamespace(telegram_bot_token="123:test-secret"))
    monkeypatch.delenv("BOT_ALLOW_DEFAULT_UID", raising=False)
    monkeypatch.delenv("WEB_URL", raising=False)
    main.run()
    assert capsys.readouterr().out == "Telegram bot configuration OK\n"
    assert "test-secret" not in repr(main.BotConfig.from_env())


def test_default_uid_is_never_implicit_demo(monkeypatch):
    monkeypatch.setattr(main, "settings", lambda: SimpleNamespace(telegram_bot_token="123:test"))
    monkeypatch.setenv("BOT_ALLOW_DEFAULT_UID", "true")
    monkeypatch.delenv("LAPSE_UID", raising=False)
    with pytest.raises(ValueError, match="explicit LAPSE_UID"):
        main.BotConfig.from_env()


def test_plan_tier_four_badge(plan, scenario):
    plan.steps = [plan.steps[3]]
    assert "T4 in person" in cards.plan_card(plan, scenario)


def test_application_registers_commands_callbacks_text_and_lifecycle():
    app = main.build_application(main.BotConfig("123:synthetic-token"))
    assert len(app.handlers[0]) == 6
    assert [handler.commands for handler in app.handlers[0][:4]] == [
        frozenset({"start"}),
        frozenset({"status"}),
        frozenset({"risk"}),
        frozenset({"help"}),
    ]
    assert app.post_init is not None
    assert app.post_shutdown is not None


async def test_smoke_prints_username_without_token(monkeypatch, capsys):
    from scripts import bot_smoke

    monkeypatch.setattr(
        bot_smoke, "settings", lambda: SimpleNamespace(telegram_bot_token="123:never-print-this")
    )

    class Bot:
        def __init__(self, token):
            assert token == "123:never-print-this"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get_me(self):
            return SimpleNamespace(username="synthetic_bot")

    monkeypatch.setattr(bot_smoke, "Bot", Bot)
    assert await bot_smoke.check() == 0
    assert capsys.readouterr().out == "TELEGRAM_BOT_TOKEN set: yes\ngetMe username: @synthetic_bot\n"


@pytest.mark.parametrize("hint", ["9810", "••9810", "old number"])
async def test_risk_hint_sends_one_answer_for_selected_phone(harness, monkeypatch, scenario, hint):
    from lapse.agent import tools
    from lapse.bot.runtime import scenarios, views

    roots = [
        Root(id="old", kind="phone", label="••9810 (Vi)", last4="9810", status="retiring"),
        Root(id="college", kind="email", label="College email", status="closing"),
    ]
    monkeypatch.setattr(views, "list_roots", lambda uid: roots)
    monkeypatch.setattr(
        tools,
        "resolve",
        lambda uid, hint: {
            "candidates": [{"id": "old", "label": "••9810 (Vi)", "kind": "root"}],
        },
    )
    run = Mock(return_value=scenario)
    monkeypatch.setattr(scenarios, "run_scenario", run)
    harness.context.args = hint.split()
    await harness.runtime.risk(harness.update, harness.context)
    assert len(harness.bot.sent) == 1
    assert run.call_count == 1
    assert run.call_args.args[1].root_ids == ["old"]
    assert "9810" in last_text(harness)
    assert "college" not in last_text(harness).lower()
