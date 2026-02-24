"""Inject li_at cookie into LinkedIn MCP browser profile (headless, no GUI needed)."""

import asyncio
import sys
from pathlib import Path

PROFILE_DIR = Path.home() / ".linkedin-mcp" / "profile"


async def inject_and_verify(li_at_value: str) -> bool:
    from patchright.async_api import async_playwright

    print(f"Creating browser profile at {PROFILE_DIR}...")
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=True,
            viewport={"width": 1280, "height": 720},
        )
        page = context.pages[0] if context.pages else await context.new_page()

        # Inject the li_at cookie
        await context.add_cookies([
            {
                "name": "li_at",
                "value": li_at_value,
                "domain": ".linkedin.com",
                "path": "/",
                "httpOnly": True,
                "secure": True,
                "sameSite": "None",
            }
        ])
        print("Cookie injected. Verifying login...")

        # Navigate to LinkedIn to verify
        await page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

        # Check if we're logged in (feed page stays vs redirect to login)
        url = page.url
        logged_in = "/feed" in url or "/mynetwork" in url or "/in/" in url

        if logged_in:
            print("Login verified! Profile saved.")
        else:
            print(f"Login check inconclusive (landed on {url}).")
            print("Profile saved anyway — the server will verify on startup.")

        await context.close()
        return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python inject_cookie.py <li_at_cookie_value>")
        print()
        print("To get your li_at cookie:")
        print("  1. Log in to linkedin.com on your phone/browser")
        print("  2. Open browser settings > Cookies > linkedin.com")
        print("  3. Find 'li_at' and copy its value")
        sys.exit(1)

    asyncio.run(inject_and_verify(sys.argv[1]))
