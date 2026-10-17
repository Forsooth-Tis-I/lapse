from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
from collections import defaultdict, deque
from contextlib import suppress
from dataclasses import dataclass
from html import escape
from importlib import import_module
from secrets import token_urlsafe
from time import monotonic
from urllib.parse import quote, urlsplit

from openai import OpenAIError
from redis.exceptions import RedisError
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction, ParseMode
from telegram.error import TelegramError

from lapse.bot import actions, cards
from lapse.contracts import ChangeStatus, GraphEvent, RootKind, RootStatus, ScenarioKind, ScenarioRequest
from lapse.graph import planner, scenarios, views

logger = logging.getLogger(__name__)


async def invoke(function, *args, **kwargs):
    if inspect.iscoroutinefunction(function):
        return await function(*args, **kwargs)
    result = await asyncio.to_thread(function, *args, **kwargs)
    return await result if inspect.isawaitable(result) else result


def dependency(name: str):
    return import_module(f"lapse.{name}")


@dataclass(frozen=True)
class PendingOTP:
    uid: str
    change_id: str
    service: str
    channel: str
    expires_at: float


class BotRuntime:
    def __init__(self, redis, *, web_url="http://localhost:5173", default_uid=None, slow_after=1.5):
        self.redis = redis
        self.web_url = web_url.rstrip("/")
        self.default_uid = default_uid
        self.slow_after = slow_after
        self.pending: dict[int, deque[PendingOTP]] = defaultdict(deque)
        self.conversations: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.otp_relays: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.delivery_task = None

    def web_link(self, path: str) -> str:
        parsed = urlsplit(path)
        if parsed.scheme or parsed.netloc or not path.startswith("/") or "\\" in path:
            raise ValueError("Web button must use a local path")
        return self.web_url + path

    async def keyboard(self, uid: str, chat_id: int, buttons: list[dict]):
        rows = []
        for button in buttons:
            action, payload = button["action"], button["payload"]
            if action == "open_web":
                item = InlineKeyboardButton(button["label"], url=self.web_link(payload["path"]))
            else:
                if action not in {"approve_changes", "plan_root", "confirm_use", "dismiss_signal"}:
                    raise ValueError("Unsupported button action")
                callback_id = "cb:" + token_urlsafe(12)
                await self.redis.set(
                    f"lapse:bot:callback:{uid}:{chat_id}:{callback_id}",
                    json.dumps({"action": action, "payload": payload}),
                    ex=900,
                )
                item = InlineKeyboardButton(button["label"], callback_data=callback_id)
            rows.append([item])
        return InlineKeyboardMarkup(rows) if rows else None

    async def send(self, bot, uid, chat_id, text, buttons=(), *, edit=None):
        keyboard = await self.keyboard(uid, chat_id, buttons)
        # Telegram counts UTF-16 units after parsing HTML; 2000 code points fit even with emoji.
        chunks = [text[i : i + 2000] for i in range(0, len(text), 2000)] or ["No reply available."]
        for index, chunk in enumerate(chunks):
            kwargs = {
                "text": escape(chunk),
                "parse_mode": ParseMode.HTML,
                "reply_markup": keyboard if index == len(chunks) - 1 else None,
            }
            if index == 0 and edit is not None:
                await edit.edit_text(**kwargs)
            else:
                await bot.send_message(chat_id=chat_id, **kwargs)

    async def uid(self, update, context):
        if update.effective_chat.type != "private":
            await update.effective_message.reply_text("Please message me in a private chat.")
            return None
        uid = await invoke(dependency("telegram_link").uid_for, update.effective_chat.id)
        if uid is None:
            await self.send(context.bot, "", update.effective_chat.id, self.onboarding())
        return uid

    def onboarding(self):
        return f"Open {self.web_url}/onboarding to get a link code, then send /start <code> here."

    async def start(self, update, context):
        chat = update.effective_chat
        if chat.type != "private":
            await update.effective_message.reply_text("Please message me in a private chat.")
            return
        link = dependency("telegram_link")
        try:
            if context.args:
                if len(context.args) != 1:
                    raise ValueError("Expected one link code")
                uid = await invoke(link.bind, context.args[0], chat.id)
            else:
                uid = await invoke(link.uid_for, chat.id)
                if uid is None and self.default_uid:
                    code = await invoke(link.new_link_code, self.default_uid)
                    uid = await invoke(link.bind, code, chat.id)
        except ValueError:
            await self.send(
                context.bot, "", chat.id, "That link code is invalid or expired. " + self.onboarding()
            )
            return
        if uid is None:
            await self.send(context.bot, "", chat.id, self.onboarding())
            return
        self.pending.pop(chat.id, None)
        await self.send(
            context.bot, uid, chat.id, "Connected. Tell me what you are changing, or use /status or /risk."
        )

    async def help(self, update, context):
        await update.effective_message.reply_text(
            "/start <code> · Connect from web onboarding\n"
            "/status · Roots, open plans and deadlines\n"
            "/risk · Risk for retiring roots\n"
            "/help · This help\n"
            "Or send a message. I will ask before taking consequential actions."
        )

    async def status(self, update, context):
        if (uid := await self.uid(update, context)) is None:
            return
        roots = await invoke(views.list_roots, uid)
        plans = await invoke(planner.list_plans, uid)
        signals = await invoke(actions.list_signals, uid)
        await self.send(context.bot, uid, update.effective_chat.id, cards.status_card(roots, plans, signals))

    async def risk(self, update, context):
        if (uid := await self.uid(update, context)) is None:
            return
        roots = await invoke(views.list_roots, uid)
        roots = [root for root in roots if root.status in {RootStatus.retiring, RootStatus.closing}]
        for root in roots:
            kind = (
                ScenarioKind.lockout
                if root.kind in {RootKind.email, RootKind.device}
                else ScenarioKind.takeover
            )
            result = await invoke(scenarios.run_scenario, uid, ScenarioRequest(kind=kind, root_ids=[root.id]))
            await self.send(
                context.bot,
                uid,
                update.effective_chat.id,
                cards.scenario_card(root, result),
                [
                    {"label": "Plan the fix", "action": "plan_root", "payload": {"root_id": root.id}},
                    {
                        "label": "Show risk",
                        "action": "open_web",
                        "payload": {"path": f"/graph?scenario={quote(result.id)}"},
                    },
                ],
            )
        if not roots:
            await self.send(context.bot, uid, update.effective_chat.id, "No retiring or closing roots yet.")

    async def text(self, update, context):
        if (uid := await self.uid(update, context)) is None:
            return
        chat_id = update.effective_chat.id
        text = update.effective_message.text.strip()
        if self.pending.get(chat_id) and re.fullmatch(r"[0-9]{4,8}", text):
            async with self.otp_relays[chat_id]:
                await self.relay_otp(update, context, uid, text)
            return
        async with self.conversations[chat_id]:
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            task = asyncio.create_task(
                invoke(dependency("agent.agent").respond, uid, text, channel="telegram")
            )
            working = None
            try:
                done, _ = await asyncio.wait({task}, timeout=self.slow_after)
                if not done:
                    working = await context.bot.send_message(chat_id=chat_id, text="Working on it…")
                while not task.done():
                    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
                    await asyncio.wait({task}, timeout=4)
                reply = task.result()
                text = reply["text"] if isinstance(reply, dict) else reply.text
                buttons = reply["buttons"] if isinstance(reply, dict) else reply.buttons
                await self.send(context.bot, uid, chat_id, text, buttons, edit=working)
            except (
                OpenAIError,
                TelegramError,
                RedisError,
                ValueError,
                TypeError,
                KeyError,
                ImportError,
                OSError,
            ):
                await self.send(
                    context.bot,
                    uid,
                    chat_id,
                    "I couldn't finish that request. Please try again.",
                    edit=working,
                )
            finally:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    if not task.done():
                        await task

    async def callback(self, update, context):
        query = update.callback_query
        await query.answer()
        if (uid := await self.uid(update, context)) is None:
            return
        chat_id = update.effective_chat.id
        if not isinstance(query.data, str) or not re.fullmatch(r"cb:[A-Za-z0-9_-]{16}", query.data):
            await query.edit_message_text("That button is invalid.")
            return
        stored = await self.redis.getdel(f"lapse:bot:callback:{uid}:{chat_id}:{query.data}")
        if stored is None:
            await query.edit_message_text("That button expired or was already used. Ask me for a fresh one.")
            return
        record = json.loads(stored)
        action, payload = record["action"], record["payload"]
        buttons = []
        if action == "approve_changes":
            approvals = dependency("approvals")
            token = payload.get("token")
            if token is None:
                token = await invoke(approvals.mint, uid, payload["change_ids"])
            change_ids = await invoke(approvals.consume, uid, token)
            approved = []
            for change_id in change_ids:
                change = await invoke(planner.update_change, uid, change_id, status=ChangeStatus.approved)
                await invoke(dependency("jobs").enqueue, uid, "execute_change", {"change_id": change_id})
                approved.append(f"• {change.account_label} · {cards.TIERS[change.tier]}")
            text = "Approved steps:\n" + "\n".join(approved)
        elif action == "plan_root":
            plan = await invoke(planner.plan_for_root, uid, payload["root_id"], payload.get("new_root_id"))
            result = await invoke(
                scenarios.run_scenario, uid, ScenarioRequest(kind=plan.kind, root_ids=[plan.old_root])
            )
            text = cards.plan_card(plan, result)
            ids = [step.id for step in plan.steps if step.tier <= 3 and step.status == ChangeStatus.proposed]
            if ids:
                buttons.append(
                    {
                        "label": "Approve all T1–T3",
                        "action": "approve_changes",
                        "payload": {"change_ids": ids},
                    }
                )
            buttons.append(
                {
                    "label": "Review steps",
                    "action": "open_web",
                    "payload": {"path": f"/plans/{quote(plan.id, safe='')}"},
                }
            )
        elif action == "confirm_use":
            await invoke(
                actions.confirm_use,
                uid,
                payload["account_id"],
                payload["root_id"],
                payload["role"],
                payload["value"],
            )
            text = (
                "Confirmed and rechecked that account."
                if payload["value"]
                else "Removed that connection and rechecked the account."
            )
        elif action == "dismiss_signal":
            await invoke(actions.dismiss_signal, uid, payload["signal_id"])
            text = "Signal dismissed."
        else:
            raise ValueError("Unsupported callback")
        await self.send(context.bot, uid, chat_id, text, buttons, edit=query.message)

    async def prompt_otp(self, bot, chat_id):
        queue = self.pending[chat_id]
        while queue and queue[0].expires_at <= monotonic():
            queue.popleft()
        if queue:
            pending = queue[0]
            await self.send(
                bot,
                pending.uid,
                chat_id,
                f"{pending.service} sent a code to {pending.channel}. Reply with it (5 min).",
            )

    async def relay_otp(self, update, context, uid, code):
        chat_id = update.effective_chat.id
        queue = self.pending[chat_id]
        pending = queue[0] if queue else None
        try:
            if pending and pending.uid == uid and pending.expires_at > monotonic():
                await invoke(dependency("otp").submit, uid, pending.change_id, code)
                self.pending[chat_id] = deque(item for item in self.pending[chat_id] if item is not pending)
                reply = "Code passed to the agent"
            else:
                if queue:
                    queue.popleft()
                reply = "There is no active code request. Ask the agent to request a new code."
        finally:
            try:
                await context.bot.delete_message(
                    chat_id=chat_id, message_id=update.effective_message.message_id
                )
            except TelegramError:
                await self.send(
                    context.bot,
                    uid,
                    chat_id,
                    "I couldn't delete your code message. Please delete it in Telegram.",
                )
        await self.send(context.bot, uid, chat_id, reply)
        await self.prompt_otp(context.bot, chat_id)

    async def deliver(self, bot, channel: str, data: dict):
        prefix, _, uid = channel.removeprefix("lapse:").partition(":")
        prefix = f"lapse:{prefix}"
        if prefix not in {"lapse:notify", "lapse:events"}:
            return
        link = dependency("telegram_link")
        chat_id = await invoke(link.chat_for, uid)
        if chat_id is None or chat_id <= 0 or await invoke(link.uid_for, chat_id) != uid:
            return
        if prefix == "lapse:notify":
            await self.send(bot, uid, chat_id, data["text"], data.get("buttons", []))
            return
        event = GraphEvent.model_validate(data)
        if event.uid != uid or event.type != "exec":
            return
        step = event.data
        if step["kind"] == "need_otp":
            change = await invoke(actions.get_change, uid, step["change_id"])
            queue = self.pending[chat_id] = deque(
                item for item in self.pending[chat_id] if item.uid == uid and item.expires_at > monotonic()
            )
            if any(item.change_id == change.id and item.uid == uid for item in queue):
                return
            queue.append(
                PendingOTP(
                    uid,
                    change.id,
                    change.account_label,
                    step.get("channel") or "your device",
                    monotonic() + 300,
                )
            )
            if len(queue) == 1:
                await self.prompt_otp(bot, chat_id)
        elif step["kind"] in {"done", "failed"}:
            queue = self.pending[chat_id]
            was_current = queue and queue[0].change_id == step["change_id"]
            self.pending[chat_id] = deque(item for item in queue if item.change_id != step["change_id"])
            if was_current:
                await self.prompt_otp(bot, chat_id)

    async def listen(self, bot):
        while True:
            try:
                async with self.redis.pubsub() as pubsub:
                    await pubsub.psubscribe("lapse:notify:*", "lapse:events:*")
                    async for message in pubsub.listen():
                        if message["type"] != "pmessage":
                            continue
                        try:
                            await self.deliver(bot, message["channel"], json.loads(message["data"]))
                        except (
                            ValueError,
                            TypeError,
                            KeyError,
                            ImportError,
                            TelegramError,
                            RedisError,
                            OSError,
                        ):
                            logger.warning(
                                "Bot delivery failed; check service availability and message schema."
                            )
            except (RedisError, OSError):
                logger.warning("Bot subscription disconnected; reconnecting.")
                await asyncio.sleep(1)

    async def startup(self, application):
        self.delivery_task = asyncio.create_task(self.listen(application.bot))

    async def shutdown(self, application):
        if self.delivery_task:
            self.delivery_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.delivery_task
        await self.redis.aclose()

    async def error(self, update, context):
        if update is None or update.effective_chat is None:
            return
        text = "I couldn't finish that request. Check /status before retrying any approval."
        if update.callback_query:
            await update.callback_query.edit_message_text(text)
        else:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=text)
