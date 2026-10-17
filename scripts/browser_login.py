"""Open the executor's browser profile for a one-time manual sign-in."""

import argparse
import asyncio
import sys

from playwright.async_api import Error as PlaywrightError

from lapse.config import settings
from lapse.exec.browser import open_browser
from lapse.exec.recipes import RECIPES


async def login(service: str, uid: str) -> None:
    recipe = next(recipe for recipe in RECIPES.values() if recipe.service_id == service)
    async with open_browser(
        uid, service, recipe.allowed_domains, headed=True, require_profile=False
    ) as context:
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(recipe.settings_url)
        await asyncio.to_thread(input, "Sign in in the browser, then press Enter here to save and close. ")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", required=True, choices=sorted({r.service_id for r in RECIPES.values()}))
    parser.add_argument("--uid", default=settings().uid)
    args = parser.parse_args()
    try:
        asyncio.run(login(args.service, args.uid))
    except (KeyboardInterrupt, EOFError):
        return 1
    except (PlaywrightError, OSError, ValueError, RuntimeError):
        print(
            "Browser sign-in could not complete. Check Chromium installation and profile availability.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
