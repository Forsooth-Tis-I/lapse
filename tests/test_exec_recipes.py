from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from playwright.async_api import Error

from lapse.contracts import Change, ChangeProcedure, Root, Service, UseRole
from lapse.exec import base, browser, inbox_codes
from lapse.exec.base import ExecContext, StepEmitter
from lapse.exec.recipes import RECIPES
from lapse.exec.recipes.dsl import (
    AwaitInboxCode,
    AwaitOTP,
    BrowserExecutor,
    Click,
    Expect,
    Fill,
    Goto,
    Recipe,
    Selector,
    SelectorFailure,
    run_recipe,
)


class FakeLocator:
    def __init__(self, page, name, role=None):
        self.page, self.name, self.role = page, name, role

    async def wait_for(self, *, state, timeout):
        self.page.actions.append(("expect", self.name, state))
        if self.name in self.page.missing:
            raise Error("selector unavailable")

    async def count(self):
        return 2 if self.name in self.page.ambiguous else 1

    async def click(self, **kwargs):
        self.page.actions.append(("click", self.name))
        if self.name in self.page.click_fails:
            raise Error("click rejected")

    async def fill(self, value, **kwargs):
        self.page.actions.append(("fill", self.name, value))

    def filter(self, **kwargs):
        self.page.actions.append(("scope", self.role, kwargs["has_text"]))
        return self

    def get_by_role(self, role, *, name, exact):
        return FakeLocator(self.page, name, role)

    def get_by_text(self, text, *, exact=True):
        return FakeLocator(self.page, text)


class FakePage:
    def __init__(self, *, missing=(), ambiguous=(), click_fails=()):
        self.actions = []
        self.missing, self.ambiguous, self.click_fails = missing, ambiguous, click_fails
        self.masks = []

    def get_by_role(self, role, *, name=None, exact=True):
        return FakeLocator(self, name, role)

    def get_by_text(self, text, *, exact=True):
        return FakeLocator(self, text)

    def locator(self, selector):
        return selector

    async def goto(self, url):
        self.actions.append(("goto", url))

    async def screenshot(self, *, path, mask):
        Path(path).write_bytes(b"fake-png")
        self.masks = mask


@pytest.fixture
def ctx():
    change = Change(
        id="change:1",
        plan_id="p",
        order=1,
        account_id="a",
        account_label="Notion",
        role="login_email",
        from_root="email_college",
        to_root="email_primary",
        tier=1,
        requires_old_root=False,
        status="running",
    )
    emitter = SimpleNamespace(emit=lambda *a, **k: None, screenshot=AsyncMock())
    return ExecContext(
        "test",
        change,
        ChangeProcedure(root_kind="email", tier=1),
        Service(id="notion", name="Notion"),
        Root(id="email_college", kind="email", label="old@example.edu", address="old@example.edu"),
        Root(id="email_primary", kind="email", label="new@example.com", address="new@example.com"),
        datetime.now(UTC),
        emitter,
    )


def recipe(*steps, confirmed=False):
    return Recipe(
        "test",
        "notion",
        (UseRole.login_email,),
        "https://notion.so/settings",
        ("notion.so",),
        steps,
        confirmed=confirmed,
    )


async def test_runner_selector_fallback_and_ambiguous_selector_never_clicked(ctx):
    page = FakePage(missing={"missing"}, ambiguous={"Edit"})
    candidate = recipe(
        Goto("https://notion.so/settings"),
        Click(
            (Selector("missing", "button"), Selector("Edit", "button"), Selector("Change email", "button"))
        ),
        Fill((Selector("Email", "textbox"),), "{new_value}"),
        Expect("{new_value}"),
        Expect("{old_value}", absent=True),
        confirmed=True,
    )
    assert await run_recipe(page, candidate, ctx) is True
    assert ("click", "Change email") in page.actions
    assert ("click", "Edit") not in page.actions
    assert ("fill", "Email", "new@example.com") in page.actions
    assert page.actions[-1] == ("expect", "old@example.edu", "hidden")
    assert ctx.emitter.screenshot.await_count == 5


async def test_inbox_proof_uses_target_inbox_and_never_emits_code(ctx, monkeypatch):
    calls, messages = [], []

    async def read(inbox, sender, subject, since):
        calls.append((inbox, sender, subject, since))
        return "123456"

    monkeypatch.setattr(inbox_codes, "await_inbox_code", read)
    ctx.emitter.emit = lambda *args, **kwargs: messages.append((args, kwargs))
    page = FakePage()
    assert (
        await run_recipe(
            page,
            recipe(
                Click((Selector("Send code", "button"),)),
                AwaitInboxCode("new", "sender", "subject"),
                Fill((Selector("Code", "textbox"),), "{code}"),
            ),
            ctx,
        )
        is False
    )
    assert calls[0][:3] == ("email_primary", "sender", "subject")
    assert calls[0][3] >= ctx.started_at
    assert ("fill", "Code", "123456") in page.actions
    assert "123456" not in str(messages)
    assert "123456" not in str(ctx.emitter.screenshot.call_args_list)


async def test_otp_wait_and_timeout(ctx, monkeypatch):
    import sys

    messages = []
    ctx.emitter.emit = lambda *args, **kwargs: messages.append((args, kwargs))
    ctx.new_root = Root(id="new", kind="phone", label="••7788", last4="7788", e164="+919000007788")
    received = []

    def wait(uid, change_id, timeout_s):
        received.append((uid, change_id, timeout_s))
        return "654321"

    monkeypatch.setitem(sys.modules, "lapse.otp", SimpleNamespace(wait=wait))
    page = FakePage()
    await run_recipe(page, recipe(AwaitOTP(), Fill((Selector("Code", "textbox"),), "{code}")), ctx)
    assert received == [("test", "change:1", 300)]
    assert ("fill", "Code", "654321") in page.actions
    assert any(args[0] == "need_otp" and kw["channel"] == "sms:••7788" for args, kw in messages)
    assert "654321" not in str(messages)
    monkeypatch.setitem(sys.modules, "lapse.otp", SimpleNamespace(wait=lambda *a, **k: None))
    with pytest.raises(TimeoutError):
        await run_recipe(page, recipe(AwaitOTP()), ctx)


async def test_off_service_link_is_blocked_without_exposing_it(ctx, monkeypatch):
    monkeypatch.setattr(
        inbox_codes, "await_inbox_code", AsyncMock(return_value="https://evil.test/verify?token=secret")
    )
    page = FakePage()
    with pytest.raises(ValueError, match="outside the allowed service") as error:
        await run_recipe(page, recipe(AwaitInboxCode("new", "sender", "subject")), ctx)
    assert "secret" not in str(error.value)
    assert not any(a[0] == "goto" for a in page.actions)


async def test_selector_failure_falls_back_with_screenshot_and_exact_link(ctx, monkeypatch):
    page = FakePage(missing={"Missing"})

    @asynccontextmanager
    async def opened(*args, **kwargs):
        yield SimpleNamespace(new_page=AsyncMock(return_value=page))

    monkeypatch.setattr(browser, "open_browser", opened)
    messages = []
    ctx.emitter.emit = lambda *args, **kwargs: messages.append((args, kwargs))
    assert await BrowserExecutor(recipe(Click((Selector("Missing"),)))).run(ctx) is False
    assert messages[-1][0][0] == "need_user"
    assert messages[-1][1]["url"] == "https://notion.so/settings"
    ctx.emitter.screenshot.assert_awaited_once()


async def test_failed_click_is_not_retried_on_another_selector(ctx):
    page = FakePage(click_fails={"Submit"})
    with pytest.raises(SelectorFailure):
        await run_recipe(page, recipe(Click((Selector("Submit"), Selector("Continue")))), ctx)
    assert ("click", "Continue") not in page.actions


async def test_screenshot_masks_fields_and_codes_and_publishes_url(tmp_path, monkeypatch):
    import json

    values, emitted = {}, []
    monkeypatch.setattr(base, "redis_client", lambda: SimpleNamespace(set=lambda k, v: values.update({k: v})))
    emitter = StepEmitter("test", "change:1", screen_dir=tmp_path)
    monkeypatch.setattr(emitter, "emit", lambda *args, **kwargs: emitted.append((args, kwargs)))
    page = FakePage()
    url = await emitter.screenshot(page, "Account settings")
    assert url == "/api/screens/test/change:1-1.png"
    assert json.loads(values["lapse:screen:test"]) == {"url": url, "caption": "Account settings"}
    assert (tmp_path / "test/change:1-1.png").stat().st_mode & 0o777 == 0o600
    assert page.masks[0] == "input, textarea, [contenteditable]"
    assert page.masks[1].name.search("123456")
    assert emitted[0][0][0] == "screenshot"


@pytest.mark.parametrize("name", tuple(RECIPES))
async def test_each_recipe_executes_with_fake_page_and_requires_terminal_state(name, ctx, monkeypatch):
    import sys

    candidate = RECIPES[name]
    if candidate.service_id == "x":
        ctx.old_root = Root(id="old", kind="phone", label="••4321", e164="+919000004321")
        ctx.new_root = Root(id="new", kind="phone", label="••7788", e164="+919000007788")
    monkeypatch.setattr(inbox_codes, "await_inbox_code", AsyncMock(return_value="123456"))
    monkeypatch.setitem(sys.modules, "lapse.otp", SimpleNamespace(wait=lambda *a, **k: "654321"))
    page = FakePage()
    assert candidate.validated is False
    assert await run_recipe(page, candidate, ctx) is True
    old = ctx.old_root.address or ctx.old_root.e164
    new = ctx.new_root.address or ctx.new_root.e164
    assert ("expect", old, "hidden") == page.actions[-1]
    assert ("expect", new, "visible") == page.actions[-2]
    failing_page = FakePage(missing={new})
    with pytest.raises(SelectorFailure):
        await run_recipe(failing_page, candidate, ctx)


async def test_verification_link_uses_temporary_context_and_never_navigates_saved_page(ctx, monkeypatch):
    link = "https://notion.so/verify?token=synthetic-secret"
    monkeypatch.setattr(inbox_codes, "await_inbox_code", AsyncMock(return_value=link))
    follow = AsyncMock()
    monkeypatch.setattr(browser, "follow_verification_link", follow)
    page = FakePage()
    candidate = recipe(AwaitInboxCode("new", "sender", "subject"))
    assert await run_recipe(page, candidate, ctx) is False
    follow.assert_awaited_once_with(page, link, ("notion.so",))
    assert not any(action[0] == "goto" for action in page.actions)
    assert "synthetic-secret" not in str(ctx.emitter.screenshot.call_args_list)


async def test_link_in_code_only_recipe_falls_back_without_filling_empty_code(ctx, monkeypatch):
    monkeypatch.setattr(
        inbox_codes, "await_inbox_code", AsyncMock(return_value="https://notion.so/verify?t=1")
    )
    monkeypatch.setattr(browser, "follow_verification_link", AsyncMock())
    page = FakePage()
    with pytest.raises(SelectorFailure, match="requires a code"):
        await run_recipe(
            page,
            recipe(
                AwaitInboxCode("new", "sender", "subject"), Fill((Selector("Code", "textbox"),), "{code}")
            ),
            ctx,
        )
    assert not any(action[0] == "fill" for action in page.actions)
