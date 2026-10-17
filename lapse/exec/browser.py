"""Persistent Chromium sessions restricted to each recipe's navigation domains."""

from __future__ import annotations

import json
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlsplit

from lapse.config import ROOT_DIR

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from playwright.async_api import BrowserContext, Page, Route

PROFILE_ROOT = ROOT_DIR / "browser_profiles"


class MissingProfile(RuntimeError):
    pass


def profile_path(uid: str, service: str) -> Path:
    for component in (uid, service):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", component):
            raise ValueError("User and service must contain only letters, digits, underscores or hyphens")
    path = PROFILE_ROOT / uid / service
    if any(part.is_symlink() for part in (PROFILE_ROOT, path.parent, path)):
        raise ValueError("Browser profile directories must not be symlinks")
    return path


def navigation_allowed(url: str, allowed_domains: tuple[str, ...]) -> bool:
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        return (
            parsed.scheme == "https"
            and parsed.username is None
            and parsed.password is None
            and any(host == domain or host.endswith("." + domain) for domain in allowed_domains)
        )
    except ValueError:
        return False


async def guard_navigation(route: Route, allowed_domains: tuple[str, ...]) -> None:
    if route.request.is_navigation_request() and not navigation_allowed(route.request.url, allowed_domains):
        await route.abort("blockedbyclient")
    else:
        await route.continue_()


async def _guard_redirects(context, page, allowed_domains):
    session = await context.new_cdp_session(page)
    await session.send("Network.enable")
    await session.send("Network.setCacheDisabled", {"cacheDisabled": True})

    async def response_paused(event):
        headers = {h["name"].lower(): h["value"] for h in event.get("responseHeaders", [])}
        location = headers.get("location")
        if location and not navigation_allowed(urljoin(event["request"]["url"], location), allowed_domains):
            await session.send(
                "Fetch.failRequest",
                {
                    "requestId": event["requestId"],
                    "errorReason": "BlockedByClient",
                },
            )
        else:
            await session.send("Fetch.continueRequest", {"requestId": event["requestId"]})

    session.on("Fetch.requestPaused", response_paused)
    await session.send(
        "Fetch.enable", {"patterns": [{"resourceType": "Document", "requestStage": "Response"}]}
    )


async def _protect_context(context: BrowserContext, allowed_domains: tuple[str, ...]) -> None:
    # Playwright skips redirect hops; Chromium must be guarded before navigation begins.
    protected_pages = set()
    original_new_page = context.new_page

    async def prepare(page):
        await _guard_redirects(context, page, allowed_domains)
        protected_pages.add(page)
        return page

    async def new_page():
        return await prepare(await original_new_page())

    async def route_request(route):
        from playwright.async_api import Error

        if route.request.is_navigation_request():
            if not navigation_allowed(route.request.url, allowed_domains):
                await route.abort("blockedbyclient")
                return
            try:
                prepared = route.request.frame.page in protected_pages
            except Error:
                prepared = False
            if not prepared:
                await route.abort("blockedbyclient")
                return
        await guard_navigation(route, allowed_domains)

    for page in context.pages:
        await prepare(page)
    context.new_page = new_page
    await context.route("**/*", route_request)


async def follow_verification_link(page: Page, url: str, allowed_domains: tuple[str, ...]) -> None:
    from playwright.async_api import Error

    if not navigation_allowed(url, allowed_domains):
        raise ValueError("Verification link is outside the allowed service")
    browser = page.context.browser
    if browser is None:
        raise RuntimeError("A Chromium browser is required for private verification")
    memory_context = await browser.new_context(
        storage_state=await page.context.storage_state(),
        service_workers="block",
        accept_downloads=False,
    )
    try:
        await _protect_context(memory_context, allowed_domains)
        verification_page = await memory_context.new_page()
        try:
            await verification_page.goto(url)
        except Error:
            raise Error("Verification link could not be completed") from None
    finally:
        await memory_context.close()
    await page.reload()


@asynccontextmanager
async def open_browser(
    uid: str,
    service: str,
    allowed_domains: tuple[str, ...],
    *,
    headed: bool | None = None,
    require_profile: bool = True,
) -> AsyncIterator[BrowserContext]:
    profile = profile_path(uid, service)
    if require_profile and (not profile.is_dir() or not any(profile.iterdir())):
        raise MissingProfile(
            f"No saved profile for {service}. Log in first: "
            f"uv run python scripts/browser_login.py --service {service} --uid {uid}"
        )
    if not allowed_domains or any(
        not re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)*", domain) for domain in allowed_domains
    ):
        raise ValueError("A recipe must supply explicit lowercase navigation domains")
    from playwright.async_api import async_playwright

    for directory in (PROFILE_ROOT, profile.parent, profile, profile / "Default"):
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory.chmod(0o700)
    preferences_path = profile / "Default" / "Preferences"
    preferences = json.loads(preferences_path.read_text()) if preferences_path.exists() else {}
    preferences["credentials_enable_service"] = False
    preferences.setdefault("profile", {})["password_manager_enabled"] = False
    preferences_path.write_text(json.dumps(preferences))
    preferences_path.chmod(0o600)
    if headed is None:
        headed = os.environ.get("EXEC_HEADED", "false").lower() == "true"
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(profile),
            headless=not headed,
            service_workers="block",
            accept_downloads=False,
            viewport={"width": 1440, "height": 900},
            args=["--disable-save-password-bubble"],
        )
        try:
            await _protect_context(context, allowed_domains)
            yield context
        finally:
            await context.close()
