from __future__ import annotations

import asyncio
import json
import re
from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from lapse.exec import browser


@pytest.mark.parametrize(
    "url",
    [
        "https://notion.so/settings",
        "https://www.notion.so/settings",
        "https://NOTION.SO/settings",
    ],
)
def test_allowlisted_hosts(url):
    assert browser.navigation_allowed(url, ("notion.so",))


@pytest.mark.parametrize(
    "url",
    [
        "https://evilnotion.so/",
        "https://notion.so.attacker.test/",
        "https://notion.so@attacker.test/",
        "https://user:secret@notion.so/",
        "http://notion.so/",
        "file:///etc/passwd",
        "data:text/html,hello",
        "https://[invalid/",
    ],
)
def test_other_navigation_is_denied(url):
    assert not browser.navigation_allowed(url, ("notion.so",))


@pytest.mark.parametrize("component", ["../demo", "", "/tmp/demo", "..", "a/b", "a\\b"])
def test_profile_path_cannot_escape_user_directory(tmp_path, monkeypatch, component):
    monkeypatch.setattr(browser, "PROFILE_ROOT", tmp_path)
    with pytest.raises(ValueError):
        browser.profile_path(component, "notion")
    with pytest.raises(ValueError):
        browser.profile_path("demo", component)


def test_profile_path_rejects_symlinks(tmp_path, monkeypatch):
    monkeypatch.setattr(browser, "PROFILE_ROOT", tmp_path / "profiles")
    (tmp_path / "profiles").mkdir()
    (tmp_path / "profiles" / "demo").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        browser.profile_path("demo", "notion")


@pytest.mark.parametrize("empty_directory", [False, True])
async def test_missing_profile_has_login_instructions(tmp_path, monkeypatch, empty_directory):
    monkeypatch.setattr(browser, "PROFILE_ROOT", tmp_path)
    if empty_directory:
        browser.profile_path("demo", "notion").mkdir(parents=True)
    with pytest.raises(browser.MissingProfile, match="browser_login.py --service notion --uid demo"):
        async with browser.open_browser("demo", "notion", ("notion.so",)):
            pytest.fail("A missing profile must never launch Chromium")


def fake_route(url, location=None, navigation=True):
    response = SimpleNamespace(headers={"location": location} if location else {}, dispose=AsyncMock())
    return SimpleNamespace(
        request=SimpleNamespace(url=url, is_navigation_request=lambda: navigation),
        abort=AsyncMock(),
        continue_=AsyncMock(),
        fetch=AsyncMock(return_value=response),
        fulfill=AsyncMock(),
    )


async def test_guard_blocks_before_request():
    route = fake_route("https://notion.so.attacker.test/")
    await browser.guard_navigation(route, ("notion.so",))
    route.abort.assert_awaited_once_with("blockedbyclient")
    route.fetch.assert_not_awaited()


async def test_guard_allows_service_navigation_and_resources():
    route = fake_route("https://notion.so/settings")
    await browser.guard_navigation(route, ("notion.so",))
    route.continue_.assert_awaited_once()
    resource = fake_route("https://cdn.test/image.png", navigation=False)
    await browser.guard_navigation(resource, ("notion.so",))
    resource.continue_.assert_awaited_once()


async def test_real_chromium_redirect_chain_and_popup_are_blocked(tmp_path, monkeypatch):
    pytest.importorskip("playwright.async_api")
    monkeypatch.setattr(browser, "PROFILE_ROOT", tmp_path / "profiles")
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            if self.path == "/first":
                self.send_response(302)
                self.send_header("Location", "/second")
            elif self.path == "/accepted":
                self.send_response(302)
                self.send_header("Location", "/settings")
            elif self.path == "/second":
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/forbidden")
            else:
                self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<html><body>Settings</body></html>")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_thread = Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    allowed = f"http://localhost:{server.server_port}"
    monkeypatch.setattr(browser, "navigation_allowed", lambda url, domains: url.startswith(allowed + "/"))
    try:
        async with browser.open_browser(
            "demo", "notion", ("notion.so",), headed=False, require_profile=False
        ) as context:
            page = await context.new_page()
            with pytest.raises(Exception, match="ERR_BLOCKED_BY_CLIENT"):
                await page.goto(allowed + "/first")
            assert requests == ["/first", "/second"]
            page = await context.new_page()
            await page.goto(allowed + "/accepted")
            assert page.url == allowed + "/settings"
            async with context.expect_page() as popup_event:
                await page.evaluate(f"window.open('http://127.0.0.1:{server.server_port}/popup')")
            popup = await popup_event.value
            await popup.wait_for_load_state()
            assert "/popup" not in requests
            async with context.expect_page() as allowed_popup_event:
                await page.evaluate(f"window.open('{allowed}/unprepared-popup')")
            allowed_popup = await allowed_popup_event.value
            await allowed_popup.wait_for_load_state()
            assert "/unprepared-popup" not in requests
            assert await page.text_content("body") == "Settings"
        profile = browser.profile_path("demo", "notion")
        assert profile.stat().st_mode & 0o777 == 0o700
        preferences = json.loads((profile / "Default" / "Preferences").read_text())
        assert preferences["profile"]["password_manager_enabled"] is False
    finally:
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        server_thread.join()


async def test_dry_run_only_navigates_and_screenshots(tmp_path, monkeypatch):
    from scripts import exec_dry_run

    page = SimpleNamespace(
        goto=AsyncMock(), locator=lambda selector: selector, get_by_text=lambda pattern: pattern
    )

    async def screenshot(**kwargs):
        Path(kwargs["path"]).write_bytes(b"png")

    page.screenshot = AsyncMock(side_effect=screenshot)

    @asynccontextmanager
    async def open_browser(*args, **kwargs):
        yield SimpleNamespace(pages=[page])

    monkeypatch.setattr(exec_dry_run, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(exec_dry_run, "open_browser", open_browser)
    await exec_dry_run.dry_run("notion", "demo")
    page.goto.assert_awaited_once()
    page.screenshot.assert_awaited_once_with(
        path=str(tmp_path / "data/screens/demo/dry-run-notion.png"),
        mask=["input, textarea, [contenteditable]", re.compile(r"\b\d{6}\b")],
    )


def test_dry_run_cli_fails_gracefully_without_profile(tmp_path, monkeypatch, capsys):
    from scripts import exec_dry_run

    monkeypatch.setattr(browser, "PROFILE_ROOT", tmp_path)
    monkeypatch.setattr("sys.argv", ["exec_dry_run.py", "--service", "notion", "--uid", "demo"])
    assert exec_dry_run.main() == 1
    captured = capsys.readouterr()
    assert "browser_login.py --service notion --uid demo" in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.parametrize(
    ("environment", "override", "expected_headless"),
    [
        ("false", None, True),
        ("true", None, False),
        ("true", False, True),
    ],
)
async def test_browser_mode_and_cleanup(tmp_path, monkeypatch, environment, override, expected_headless):
    import playwright.async_api

    context = SimpleNamespace(pages=[], new_page=AsyncMock(), route=AsyncMock(), close=AsyncMock())
    launch = AsyncMock(return_value=context)

    @asynccontextmanager
    async def fake_playwright():
        yield SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=launch))

    monkeypatch.setattr(browser, "PROFILE_ROOT", tmp_path)
    monkeypatch.setenv("EXEC_HEADED", environment)
    monkeypatch.setattr(playwright.async_api, "async_playwright", fake_playwright)
    with pytest.raises(RuntimeError, match="recipe failed"):
        async with browser.open_browser(
            "demo", "notion", ("notion.so",), headed=override, require_profile=False
        ):
            raise RuntimeError("recipe failed")
    assert launch.await_args.kwargs["headless"] is expected_headless
    assert launch.await_args.kwargs["service_workers"] == "block"
    context.close.assert_awaited_once()


@pytest.mark.parametrize("redirect_outside", [False, True])
async def test_verification_link_stays_out_of_persistent_profile(tmp_path, monkeypatch, redirect_outside):
    from playwright.async_api import Error

    monkeypatch.setattr(browser, "PROFILE_ROOT", tmp_path / "profiles")
    token = "synthetic-verification-token-9d4e825a"
    verified = False
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            nonlocal verified
            requests.append(self.path)
            if self.path.startswith("/verify?"):
                if redirect_outside:
                    self.send_response(302)
                    self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/forbidden")
                    self.end_headers()
                    return
                verified = self.headers.get("Cookie") == "session=test-session"
                self.send_response(200)
                self.send_header("Cache-Control", "public, max-age=86400")
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(
                    f"<html><body>{token}<script>localStorage.setItem('token', '{token}')</script></body></html>".encode()
                )
            else:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"Verified" if verified else b"Unverified")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_thread = Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    allowed = f"http://localhost:{server.server_port}"
    monkeypatch.setattr(browser, "navigation_allowed", lambda url, domains: url.startswith(allowed + "/"))
    try:
        async with browser.open_browser(
            "demo", "notion", ("notion.so",), headed=False, require_profile=False
        ) as context:
            await context.add_cookies([{"name": "session", "value": "test-session", "url": allowed}])
            page = await context.new_page()
            await page.goto(allowed + "/settings")
            if redirect_outside:
                with pytest.raises(Error, match="^Verification link could not be completed$"):
                    await browser.follow_verification_link(
                        page, f"{allowed}/verify?token={token}", ("notion.so",)
                    )
                assert "/forbidden" not in requests
            else:
                await browser.follow_verification_link(
                    page, f"{allowed}/verify?token={token}", ("notion.so",)
                )
                assert verified
                assert await page.text_content("body") == "Verified"
            assert page.url == allowed + "/settings"
            assert context.browser.contexts == [context]
        for path in browser.profile_path("demo", "notion").rglob("*"):
            if path.is_file():
                contents = path.read_bytes()
                assert token.encode() not in contents, path.relative_to(tmp_path)
                assert token.encode("utf-16-le") not in contents, path.relative_to(tmp_path)
    finally:
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        server_thread.join()
