from __future__ import annotations

import argparse
import logging
import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from redis.asyncio import Redis
from telegram.error import TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from lapse.bot.runtime import BotRuntime
from lapse.config import settings


@dataclass(frozen=True)
class BotConfig:
    token: str = field(repr=False)
    web_url: str = "http://localhost:5173"
    default_uid: str | None = None

    @classmethod
    def from_env(cls):
        token = settings().telegram_bot_token.strip()
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN is required to run the Telegram bot.")
        web_url = os.environ.get("WEB_URL", "http://localhost:5173").rstrip("/")
        parsed = urlsplit(web_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("WEB_URL must be an HTTP(S) base URL without a query or fragment.")
        default_uid = None
        if os.environ.get("BOT_ALLOW_DEFAULT_UID", "false").lower() == "true":
            default_uid = os.environ.get("LAPSE_UID", "").strip()
            if not default_uid:
                raise ValueError("BOT_ALLOW_DEFAULT_UID=true requires an explicit LAPSE_UID.")
        return cls(token, web_url, default_uid)


def build_application(config: BotConfig) -> Application:
    connection = settings()
    runtime = BotRuntime(
        Redis(host=connection.falkordb_host, port=connection.falkordb_port, decode_responses=True),
        web_url=config.web_url,
        default_uid=config.default_uid,
    )
    app = (
        Application.builder()
        .token(config.token)
        .concurrent_updates(True)
        .post_init(runtime.startup)
        .post_shutdown(runtime.shutdown)
        .build()
    )
    for name in ("start", "status", "risk", "help"):
        app.add_handler(CommandHandler(name, getattr(runtime, name)))
    app.add_handler(CallbackQueryHandler(runtime.callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, runtime.text))
    app.add_error_handler(runtime.error)
    return app


def run():
    parser = argparse.ArgumentParser(description="Lapse Telegram bot")
    parser.add_argument("--check", action="store_true", help="Validate configuration without polling")
    args = parser.parse_args()
    try:
        config = BotConfig.from_env()
    except ValueError as exc:
        parser.exit(2, f"{exc}\n")
    if args.check:
        print("Telegram bot configuration OK")
        return
    for name in ("httpx", "httpcore", "telegram"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    try:
        build_application(config).run_polling(allowed_updates=["message", "callback_query"])
    except (TelegramError, ValueError, RuntimeError, OSError):
        parser.exit(1, "Telegram bot stopped. Check configuration and service availability.\n")


if __name__ == "__main__":
    run()
