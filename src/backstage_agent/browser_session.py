from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from .settings import Settings


BACKSTAGE_HOME_URL = "https://www.backstage.com/"
BACKSTAGE_LOGIN_URL = "https://www.backstage.com/accounts/"


@dataclass(frozen=True)
class LoginCheck:
    logged_in: bool
    url: str
    title: str
    reason: str


class BrowserSessionError(RuntimeError):
    pass


def open_backstage_login(settings: Settings) -> None:
    _run(_open_backstage_login(settings))


def check_backstage_login(settings: Settings) -> LoginCheck:
    return _run(_check_backstage_login(settings))


def fetch_authenticated_html(settings: Settings, url: str | None) -> str | None:
    if not url:
        return None
    return _run(_fetch_authenticated_html(settings, url))


async def _open_backstage_login(settings: Settings) -> None:
    async with _browser_context(settings, headless=False) as context:
        page = await context.new_page()
        await page.goto(BACKSTAGE_LOGIN_URL, wait_until="domcontentloaded")
        print(f"Opened Backstage login in persistent profile: {settings.browser_profile_path}")
        print("Log in there, then close the browser window when you are done.")
        await page.wait_for_event("close", timeout=0)


async def _check_backstage_login(settings: Settings) -> LoginCheck:
    async with _browser_context(settings, headless=settings.backstage_browser_headless) as context:
        page = await context.new_page()
        await page.goto(BACKSTAGE_HOME_URL, wait_until="domcontentloaded")
        return await _login_check_from_page(page)


async def _fetch_authenticated_html(settings: Settings, url: str) -> str:
    async with _browser_context(settings, headless=settings.backstage_browser_headless) as context:
        page = await context.new_page()
        await page.goto(url, wait_until="domcontentloaded")
        check = await _login_check_from_page(page)
        if not check.logged_in:
            raise BrowserSessionError(
                f"Backstage login required for authenticated page fetch: {check.reason}"
            )
        return await page.content()


async def _login_check_from_page(page) -> LoginCheck:
    text = await page.locator("body").inner_text(timeout=10_000)
    title = await page.title()
    url = page.url
    normalized = " ".join(text.split()).lower()
    if "cloudflare" in normalized or "attention required" in title.lower():
        return LoginCheck(
            logged_in=False,
            url=url,
            title=title,
            reason="Backstage showed a Cloudflare challenge instead of the logged-in site.",
        )
    if "sign in" in normalized and "join" in normalized:
        return LoginCheck(
            logged_in=False,
            url=url,
            title=title,
            reason="Backstage shows sign-in/join controls.",
        )
    if "log into view additional details" in normalized:
        return LoginCheck(
            logged_in=False,
            url=url,
            title=title,
            reason="Backstage says login is required to view details.",
        )
    return LoginCheck(
        logged_in=True,
        url=url,
        title=title,
        reason="No sign-in gate detected.",
    )


class _browser_context:
    def __init__(self, settings: Settings, headless: bool):
        self.settings = settings
        self.headless = headless
        self.playwright = None
        self.context = None

    async def __aenter__(self):
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise BrowserSessionError(
                "Playwright is not installed. Run `pip install -e .` and "
                "`python -m playwright install chromium`."
            ) from exc

        self.settings.browser_profile_path.mkdir(parents=True, exist_ok=True)
        self.playwright = await async_playwright().start()
        launch_options = {
            "user_data_dir": str(self.settings.browser_profile_path),
            "headless": self.headless,
            "viewport": {"width": 1280, "height": 900},
        }
        if self.settings.backstage_browser_channel:
            launch_options["channel"] = self.settings.backstage_browser_channel
        try:
            self.context = await self.playwright.chromium.launch_persistent_context(**launch_options)
        except Exception as exc:  # noqa: BLE001
            if self.settings.backstage_browser_channel:
                launch_options.pop("channel", None)
                try:
                    self.context = await self.playwright.chromium.launch_persistent_context(
                        **launch_options
                    )
                    return self.context
                except Exception:
                    pass
            await self.playwright.stop()
            raise BrowserSessionError(
                "Could not start the persistent Backstage browser profile. "
                "If this is the first setup, run `python -m playwright install chromium`."
            ) from exc
        return self.context

    async def __aexit__(self, exc_type, exc, tb):
        if self.context is not None:
            await self.context.close()
        if self.playwright is not None:
            await self.playwright.stop()


def _run(coro):
    try:
        return asyncio.run(coro)
    except KeyboardInterrupt:
        raise


def default_browser_profile_path(project_root: Path | None = None) -> Path:
    root = project_root or Path.cwd()
    return root / "browser_profiles" / "backstage"
