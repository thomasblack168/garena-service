from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from playwright.async_api import async_playwright

OAUTH_URL = (
    "https://authgop.garena.com/universal/oauth"
    "?client_id=10017&redirect_uri=https%3A%2F%2Ftermgame.com%2F"
    "&response_type=code&platform=1&locale=th-TH&theme=light"
    "&state=https%3A%2F%2Ftermgame.com%2F"
)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)


@dataclass
class LoginTestResult:
    ok: bool
    final_url: str
    cookie_names: list[str] = field(default_factory=list)
    body_snippet: str = ""
    error: str | None = None


async def test_login(email: str, password: str, *, proxy: str | None = None) -> LoginTestResult:
    proxy = proxy if proxy is not None else os.environ.get("TERMGAME_HTTP_PROXY", "").strip()
    launch_kwargs: dict[str, Any] = {"headless": True}
    if proxy:
        launch_kwargs["proxy"] = {"server": proxy}

    async with async_playwright() as p:
        browser = await p.chromium.launch(**launch_kwargs)
        try:
            context = await browser.new_context(
                user_agent=_UA,
                viewport={"width": 1366, "height": 900},
                locale="th-TH",
            )
            page = await context.new_page()

            try:
                await page.goto(OAUTH_URL, wait_until="load", timeout=30_000)
            except Exception as exc:
                return LoginTestResult(ok=False, final_url="", error=f"goto_failed: {exc}")

            await page.wait_for_timeout(1_200)

            try:
                await page.screenshot(path="/tmp/login_debug_1_loaded.png")
            except Exception:
                pass

            try:
                await page.fill("input[type='text']", email, timeout=10_000)
                await page.fill("input[type='password']", password, timeout=10_000)
                try:
                    await page.screenshot(path="/tmp/login_debug_2_filled.png")
                except Exception:
                    pass
                await page.click("button[type='submit']", timeout=10_000)
            except Exception as exc:
                return LoginTestResult(
                    ok=False,
                    final_url=page.url,
                    error=f"form_interaction_failed: {exc}",
                )

            await page.wait_for_timeout(4_000)
            try:
                await page.screenshot(path="/tmp/login_debug_3_after_submit.png", full_page=True)
            except Exception:
                pass

            final_url = page.url
            body_text = ""
            try:
                body_text = await page.inner_text("body")
            except Exception:
                pass

            cookies = await context.cookies()
            cookie_names = [c["name"] for c in cookies]

            success = "termgame.com" in final_url and "authgop" not in final_url

            return LoginTestResult(
                ok=success,
                final_url=final_url,
                cookie_names=cookie_names,
                body_snippet=body_text[:400],
            )
        finally:
            await browser.close()
