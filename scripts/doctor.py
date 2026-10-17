"""Check local deployment prerequisites without displaying configuration values."""

from __future__ import annotations

import argparse
import imaplib
import re
import socket
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

import httpx
from dotenv.parser import parse_stream
from openai import OpenAIError
from redis import Redis
from redis.exceptions import RedisError

from lapse import llm

REQUIRED = (
    "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL", "TELEGRAM_BOT_TOKEN",
    "LAPSE_SECRET_KEY", "APPROVAL_SIGNING_KEY", "FALKORDB_HOST", "FALKORDB_PORT",
)
PORTS = (6380, 3001, 8000, 8766, 8080)
TIMEOUT = 5
PLACEHOLDER = re.compile(r"xxxx|you\.demo|change[-_ ]?me|replace[-_ ]?me|<[^>]+>", re.IGNORECASE)


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str

    def render(self) -> str:
        return f"{'✓' if self.ok else '✗'} {self.name}: {self.detail}"


def has_placeholder(value: str) -> bool:
    return bool(PLACEHOLDER.search(value))


def mask(value: str) -> str:
    return f"<set, {len(value)} chars>" if value else "<unset>"


def parse_env(text: str) -> dict[str, str]:
    """Parse dotenv quoting without expanding variables or logging malformed lines."""
    result = {}
    for binding in parse_stream(StringIO(text)):
        if binding.error:
            raise ValueError("Invalid dotenv syntax")
        if binding.key is not None:
            result[binding.key] = binding.value or ""
    return result


def configured(env: dict[str, str], *names: str) -> bool:
    return all(env.get(name, "").strip() and not has_placeholder(env[name]) for name in names)


def check_falkordb(env: dict[str, str]) -> Check:
    hint = "Start FalkorDB v4.22.1 and check FALKORDB_HOST/PORT."
    if not configured(env, "FALKORDB_HOST", "FALKORDB_PORT"):
        return Check("FalkorDB", False, hint)
    try:
        with Redis(
            host=env["FALKORDB_HOST"], port=int(env["FALKORDB_PORT"]),
            socket_connect_timeout=TIMEOUT, socket_timeout=TIMEOUT, decode_responses=True,
        ) as client:
            modules = client.module_list()
        found = any(m.get("name") in ("graph", "falkordb") and m.get("ver") == 42201 for m in modules)
        return Check("FalkorDB", found, "Graph module version 42201." if found else hint)
    except (OSError, ValueError, RedisError):
        return Check("FalkorDB", False, hint)


def check_llm(env: dict[str, str]) -> Check:
    hint = "Check LLM_BASE_URL, LLM_API_KEY and LLM_MODEL; chat completion must succeed."
    if not configured(env, "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        return Check("LLM", False, hint)
    try:
        with llm.client(base_url=env["LLM_BASE_URL"], api_key=env["LLM_API_KEY"]) as connection:
            response = llm.complete(
                connection,
                messages=[{"role": "user", "content": "Reply OK."}],
                max_tokens=1,
                model=env["LLM_MODEL"],
                fallback_models="",
            )
        ok = bool(response.choices)
        return Check("LLM", ok, "One-token chat completion succeeded." if ok else hint)
    except (OpenAIError, ValueError, TypeError, AttributeError):
        return Check("LLM", False, hint)


def check_telegram(env: dict[str, str]) -> Check:
    hint = "Set a working TELEGRAM_BOT_TOKEN from BotFather."
    if not configured(env, "TELEGRAM_BOT_TOKEN"):
        return Check("Telegram", False, hint)
    try:
        response = httpx.get(
            "https://api.telegram.org/bot" + env["TELEGRAM_BOT_TOKEN"] + "/getMe", timeout=TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        username = payload.get("result", {}).get("username", "")
        if payload.get("ok") and re.fullmatch(r"[A-Za-z0-9_]{1,64}", username):
            return Check("Telegram", True, f"Bot @{username} authenticated.")
    except (httpx.HTTPError, httpx.InvalidURL, ValueError, TypeError, AttributeError):
        return Check("Telegram", False, hint)
    return Check("Telegram", False, hint)


def check_imap(env: dict[str, str]) -> list[Check]:
    checks = []
    for prefix in ("PRIMARY", "COLLEGE"):
        names = tuple(f"{prefix}_IMAP_{field}" for field in ("HOST", "USER", "PASSWORD"))
        if not any(env.get(name, "").strip() for name in names[1:]):
            checks.append(Check(f"{prefix} IMAP", True, "Not configured; skipped."))
            continue
        hint = f"Check {prefix}_IMAP_HOST/USER/PASSWORD and enable IMAP with an app password."
        if not configured(env, *names):
            checks.append(Check(f"{prefix} IMAP", False, hint))
            continue
        try:
            with imaplib.IMAP4_SSL(env[names[0]], timeout=TIMEOUT) as client:
                client.login(env[names[1]], env[names[2]])
            checks.append(Check(f"{prefix} IMAP", True, "Login and logout succeeded."))
        except (OSError, imaplib.IMAP4.error, ValueError):
            checks.append(Check(f"{prefix} IMAP", False, hint))
    return checks


def check_chromium() -> Check:
    hint = "Run uv sync --extra browser, then uv run playwright install --with-deps chromium."
    try:
        from playwright.sync_api import Error, sync_playwright
    except ImportError:
        return Check("Playwright Chromium", False, hint)
    try:
        with sync_playwright() as playwright:
            installed = Path(playwright.chromium.executable_path).is_file()
        return Check("Playwright Chromium", installed, "Browser installed." if installed else hint)
    except (OSError, Error):
        return Check("Playwright Chromium", False, hint)


def check_ports() -> list[Check]:
    checks = []
    for port in PORTS:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(("0.0.0.0", port))
            checks.append(Check(f"Host port {port}", True, "Available."))
        except OSError:
            checks.append(Check(
                f"Host port {port}", False,
                "In use; expected if Lapse is already running. Otherwise stop the conflicting service.",
            ))
    return checks


def run_checks(root: Path) -> list[Check]:
    checks = []
    env = {}
    try:
        env = parse_env((root / ".env").read_text())
        checks.append(Check(".env", True, "File exists and parses."))
    except FileNotFoundError:
        checks.append(Check(".env", False, "Copy .env.example to .env and fill in the required values."))
    except (OSError, UnicodeError, ValueError):
        checks.append(Check(".env", False, "Fix file permissions, encoding or dotenv syntax."))
    missing = [name for name in REQUIRED if not configured(env, name)]
    checks.append(Check(
        "Required variables", not missing,
        "Set non-placeholder values for: " + ", ".join(missing) if missing else "All set.",
    ))
    try:
        text = (root / "persona.local.yaml").read_text()
        clean = bool(text.strip()) and not has_placeholder(text)
        checks.append(Check(
            "persona.local.yaml", clean,
            "No placeholder patterns found." if clean else "Replace placeholder values in persona.local.yaml.",
        ))
    except (OSError, UnicodeError):
        checks.append(Check("persona.local.yaml", False, "Create a readable persona.local.yaml from the example."))
    checks.extend((check_falkordb(env), check_llm(env), check_telegram(env)))
    checks.extend(check_imap(env))
    checks.append(check_chromium())
    checks.extend(check_ports())
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    checks = run_checks(args.root)
    for check in checks:
        print(check.render())
    return int(any(not check.ok for check in checks))


if __name__ == "__main__":
    raise SystemExit(main())
