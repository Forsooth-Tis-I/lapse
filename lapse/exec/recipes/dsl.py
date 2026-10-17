from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from lapse.contracts import Change, UseRole
from lapse.exec.base import ExecContext


@dataclass(frozen=True)
class Selector:
    name: str | re.Pattern[str]
    role: str | None = None
    within: str | None = None
    container_role: str | None = "row"


@dataclass(frozen=True)
class Goto:
    url: str
    ready: Selector | None = None


@dataclass(frozen=True)
class Click:
    selectors: tuple[Selector, ...]
    ready: Selector | None = None


@dataclass(frozen=True)
class Fill:
    selectors: tuple[Selector, ...]
    value: str


@dataclass(frozen=True)
class AwaitInboxCode:
    inbox: Literal["old", "new"]
    sender_pattern: str
    subject_pattern: str
    code_pattern: str | None = None


@dataclass(frozen=True)
class AwaitOTP:
    channel: str = "sms"


@dataclass(frozen=True)
class Expect:
    text: str
    absent: bool = False


@dataclass(frozen=True)
class Screenshot:
    caption: str


Step = Goto | Click | Fill | AwaitInboxCode | AwaitOTP | Expect | Screenshot


@dataclass(frozen=True)
class Recipe:
    name: str
    service_id: str
    roles: tuple[UseRole, ...]
    settings_url: str
    allowed_domains: tuple[str, ...]
    steps: tuple[Step, ...]
    validated: bool = False
    confirmed: bool = False


class SelectorFailure(RuntimeError):
    pass


async def _select(page, selectors: tuple[Selector, ...], values: dict[str, str], *, timeout_ms=10000):
    from playwright.async_api import Error

    for selector in selectors:
        parent = page
        if selector.within is not None:
            within = selector.within.format_map(values)
            parent = (
                page.get_by_role(selector.container_role).filter(has_text=within)
                if selector.container_role
                else page.get_by_text(within, exact=True).locator("..")
            )
        name = selector.name.format_map(values) if isinstance(selector.name, str) else selector.name
        locator = (
            parent.get_by_role(selector.role, name=name, exact=True)
            if selector.role
            else parent.get_by_text(name, exact=True)
        )
        try:
            await locator.wait_for(state="visible", timeout=timeout_ms)
        except Error:
            continue
        if await locator.count() == 1:
            return locator
    raise SelectorFailure("The expected account control was unavailable or ambiguous")


async def navigate(page, step: Goto, allowed_domains: tuple[str, ...]) -> None:
    from lapse.exec.browser import navigation_allowed

    if not navigation_allowed(step.url, allowed_domains):
        raise ValueError("Recipe navigation is outside the allowed service")
    await page.goto(step.url, wait_until="domcontentloaded")
    if step.ready is not None:
        await _select(page, (step.ready,), {}, timeout_ms=30000)


async def run_recipe(page, recipe: Recipe, ctx: ExecContext) -> bool:
    from playwright.async_api import Error

    from lapse.exec.browser import follow_verification_link, navigation_allowed
    from lapse.exec.inbox_codes import await_inbox_code

    if ctx.new_root is None:
        raise ValueError("Browser recipes require a replacement root")
    values = {
        "old_value": ctx.old_root.address or ctx.old_root.e164 or "",
        "new_value": ctx.new_root.address or ctx.new_root.e164 or "",
    }
    if not all(values.values()):
        raise ValueError("Browser recipes require complete contact values")
    since = datetime.now(UTC)
    try:
        for number, step in enumerate(recipe.steps, 1):
            ctx.emitter.emit("progress", f"{ctx.service.name}: step {number} of {len(recipe.steps)}")
            try:
                match step:
                    case Goto():
                        await navigate(page, step, recipe.allowed_domains)
                    case Click(selectors, ready):
                        locator = await _select(page, selectors, values)
                        since = datetime.now(UTC)
                        await locator.click(timeout=5000)
                        if ready is not None:
                            await _select(page, (ready,), values)
                    case Fill(selectors, value):
                        locator = await _select(page, selectors, values)
                        if "{code}" in value and "code" not in values:
                            raise SelectorFailure("This page requires a code; the inbox returned a link")
                        await locator.fill(value.format_map(values), timeout=5000)
                        if "{code}" in value:
                            values.pop("code", None)
                    case AwaitInboxCode(inbox, sender_pattern, subject_pattern, code_pattern):
                        root = ctx.old_root if inbox == "old" else ctx.new_root
                        options = {"code_pattern": code_pattern} if code_pattern is not None else {}
                        code = await await_inbox_code(
                            root.id, sender_pattern, subject_pattern, since, **options
                        )
                        if code.startswith("https://"):
                            if not navigation_allowed(code, recipe.allowed_domains):
                                raise ValueError("Verification link is outside the allowed service")
                            await follow_verification_link(page, code, recipe.allowed_domains)
                        else:
                            values["code"] = code
                        code = None
                    case AwaitOTP(channel):
                        from lapse.otp import wait

                        suffix = ctx.new_root.last4 or (ctx.new_root.e164 or "")[-4:]
                        ctx.emitter.emit(
                            "need_otp",
                            f"Enter the SMS code for {ctx.service.name} in Telegram.",
                            channel=f"{channel}:••{suffix}",
                        )
                        code = await asyncio.to_thread(wait, ctx.uid, ctx.change.id, timeout_s=300)
                        if not code:
                            raise TimeoutError("SMS confirmation timed out")
                        values["code"] = code
                        code = None
                    case Expect(text, absent):
                        await page.get_by_text(text.format_map(values), exact=True).wait_for(
                            state="hidden" if absent else "visible", timeout=10000
                        )
                    case Screenshot(caption):
                        await ctx.emitter.screenshot(page, caption)
                if not isinstance(step, Screenshot):
                    await ctx.emitter.screenshot(page, f"{ctx.service.name}: step {number}")
            except Error:
                raise SelectorFailure("The account page no longer matches this recipe") from None
        return recipe.confirmed
    finally:
        values.clear()


@dataclass
class BrowserExecutor:
    recipe: Recipe

    def can_run(self, change: Change) -> bool:
        return change.tier in {1, 2} and change.role in self.recipe.roles and change.to_root is not None

    async def run(self, ctx: ExecContext) -> bool:
        from playwright.async_api import Error

        from lapse.exec.browser import MissingProfile, open_browser
        from lapse.exec.t3_assisted import AssistedExecutor

        try:
            async with open_browser(ctx.uid, self.recipe.service_id, self.recipe.allowed_domains) as browser:
                page = await browser.new_page()
                try:
                    return await run_recipe(page, self.recipe, ctx)
                except SelectorFailure:
                    if self.recipe.validated:
                        raise
                    await ctx.emitter.screenshot(page, "Automation paused; finish this change in settings")
                    return await AssistedExecutor().run(ctx, url=self.recipe.settings_url)
        except MissingProfile:
            return await AssistedExecutor().run(ctx, url=self.recipe.settings_url)
        except Error:
            raise RuntimeError("Browser session unavailable") from None
