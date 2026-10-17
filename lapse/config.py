"""Settings read from the environment (.env in development). Never log secret values."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    falkordb_host: str
    falkordb_port: int
    uid: str
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    telegram_bot_token: str
    secret_key: str
    approval_signing_key: str
    demo_mode: bool


@lru_cache
def settings() -> Settings:
    e = os.environ.get
    return Settings(
        falkordb_host=e("FALKORDB_HOST", "localhost"),
        falkordb_port=int(e("FALKORDB_PORT", "6380")),
        uid=e("LAPSE_UID", "demo"),
        llm_base_url=e("LLM_BASE_URL", "https://opencode.ai/zen/v1"),
        llm_api_key=e("LLM_API_KEY", ""),
        llm_model=e("LLM_MODEL", "deepseek-v4.1-flash-free"),
        telegram_bot_token=e("TELEGRAM_BOT_TOKEN", ""),
        secret_key=e("LAPSE_SECRET_KEY", ""),
        approval_signing_key=e("APPROVAL_SIGNING_KEY", ""),
        demo_mode=e("LAPSE_DEMO_MODE", "false").lower() == "true",
    )
