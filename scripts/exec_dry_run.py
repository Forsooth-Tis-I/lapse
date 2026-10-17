"""Open account settings and take a screenshot without executing any change steps."""

import argparse
import asyncio
import re
import sys

from playwright.async_api import Error as PlaywrightError

from lapse.config import ROOT_DIR, settings
from lapse.exec.browser import MissingProfile, open_browser
from lapse.exec.recipes import RECIPES


async def dry_run(service: str, uid: str) -> None:
    recipe = next(recipe for recipe in RECIPES.values() if recipe.service_id == service)
    async with open_browser(uid, service, recipe.allowed_domains) as context:
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(recipe.settings_url)
        directory = ROOT_DIR / "data" / "screens" / uid
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        screenshot = directory / f"dry-run-{service}.png"
        await page.screenshot(
            path=str(screenshot),
            mask=[
                page.locator("input, textarea, [contenteditable]"),
                page.get_by_text(re.compile(r"\b\d{6}\b")),
            ],
        )
        screenshot.chmod(0o600)
        print(f"Settings screenshot: {screenshot}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", required=True, choices=sorted({r.service_id for r in RECIPES.values()}))
    parser.add_argument("--uid", default=settings().uid)
    args = parser.parse_args()
    try:
        asyncio.run(dry_run(args.service, args.uid))
    except MissingProfile as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (PlaywrightError, OSError, ValueError, RuntimeError):
        print(
            "Dry run could not open settings. Check the saved login and Chromium installation.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
