import asyncio
import logging

from telegram import Bot
from telegram.error import TelegramError

from lapse.config import settings


async def check():
    token = settings().telegram_bot_token.strip()
    print(f"TELEGRAM_BOT_TOKEN set: {'yes' if token else 'no'}")
    if not token:
        return 1
    for name in ("httpx", "httpcore", "telegram"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    try:
        async with Bot(token) as bot:
            me = await bot.get_me()
            print(f"getMe username: @{me.username}")
        return 0
    except (TelegramError, ValueError, OSError):
        print("getMe failed. Check the token and network connection.")
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(check()))
