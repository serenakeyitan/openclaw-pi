"""Test LinkedIn auth: inject cookie, navigate, screenshot what we see."""

import asyncio
import sys
from pathlib import Path

PROFILE_DIR = Path.home() / ".linkedin-mcp" / "profile"
SCREENSHOT_PATH = Path("/tmp/linkedin_test.png")


async def test(li_at_value: str):
    from patchright.async_api import async_playwright

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=True,
            viewport={"width": 1280, "height": 720},
        )
        page = context.pages[0] if context.pages else await context.new_page()

        # Inject cookie
        await context.add_cookies([{
            "name": "li_at",
            "value": li_at_value,
            "domain": ".linkedin.com",
            "path": "/",
            "httpOnly": True,
            "secure": True,
            "sameSite": "None",
        }])

        # Navigate
        print("Navigating to LinkedIn feed...")
        await page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_timeout(8000)

        # Screenshot
        await page.screenshot(path=str(SCREENSHOT_PATH))
        print(f"Screenshot saved to {SCREENSHOT_PATH}")

        # Report
        url = page.url
        title = await page.title()
        print(f"URL: {url}")
        print(f"Title: {title}")

        logged_in = "/feed" in url and "login" not in url
        print(f"Logged in: {logged_in}")

        await context.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_auth.py <li_at_value>")
        sys.exit(1)
    asyncio.run(test(sys.argv[1]))
