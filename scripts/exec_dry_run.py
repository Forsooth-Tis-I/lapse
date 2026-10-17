"""Open account settings and take a screenshot without executing any change steps."""

import argparse
import asyncio
import sys

from playwright.async_api import Error as PlaywrightError

from lapse.config import ROOT_DIR, settings
from lapse.exec.base import save_screenshot
from lapse.exec.browser import MissingProfile, open_browser
from lapse.exec.recipes import RECIPES
from lapse.exec.recipes.dsl import Goto, navigate


async def dry_run(service: str, uid: str) -> None:
    recipe = next(recipe for recipe in RECIPES.values() if recipe.service_id == service)
    async with open_browser(uid, service, recipe.allowed_domains) as context:
        page = context.pages[0] if context.pages else await context.new_page()
        first_step = recipe.steps[0]
        if not isinstance(first_step, Goto):
            raise TypeError("A dry-run recipe must start with navigation")
        await navigate(page, first_step, recipe.allowed_domains)
        if first_step.ready is None:
            await page.wait_for_load_state("networkidle")
            await page.get_by_role("button").first.wait_for(state="visible", timeout=30000)
        directory = ROOT_DIR / "data" / "screens" / uid
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        screenshot = directory / f"dry-run-{service}.png"
        await save_screenshot(page, screenshot)
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
    except (PlaywrightError, OSError, ValueError, TypeError, RuntimeError):
        print(
            "Dry run could not open settings. Check the saved login and Chromium installation.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
