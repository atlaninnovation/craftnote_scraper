from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Final

from playwright.async_api import Browser, BrowserContext, Page, ViewportSize, async_playwright

DEFAULT_USER_DATA_DIR: Final[Path] = Path.home() / ".craftnote_scraper" / "browser_data"
DEFAULT_VIEWPORT_WIDTH: Final[int] = 1280
DEFAULT_VIEWPORT_HEIGHT: Final[int] = 720
DEFAULT_USER_AGENT: Final[str] = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
BRAVE_EXECUTABLE_PATH: Final[Path] = Path(
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
)


class BrowserConfig:
    def __init__(
        self,
        headless: bool = True,
        user_data_dir: Path | None = None,
        viewport_width: int = DEFAULT_VIEWPORT_WIDTH,
        viewport_height: int = DEFAULT_VIEWPORT_HEIGHT,
        user_agent: str = DEFAULT_USER_AGENT,
        executable_path: Path | None = None,
    ):
        self.headless = headless
        self.user_data_dir = user_data_dir or DEFAULT_USER_DATA_DIR
        self.viewport_width = viewport_width
        self.viewport_height = viewport_height
        self.user_agent = user_agent
        self.executable_path = executable_path


@asynccontextmanager
async def browser_context(config: BrowserConfig | None = None) -> AsyncIterator[BrowserContext]:
    """Create a browser context with persistent storage for session reuse."""
    cfg = config or BrowserConfig()
    cfg.user_data_dir.mkdir(parents=True, exist_ok=True)

    viewport: ViewportSize = {"width": cfg.viewport_width, "height": cfg.viewport_height}
    executable_path: Path | str | None = cfg.executable_path

    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=cfg.user_data_dir,
            headless=cfg.headless,
            viewport=viewport,
            user_agent=cfg.user_agent,
            executable_path=executable_path,
        )
        try:
            yield context
        finally:
            await context.close()


@asynccontextmanager
async def new_page(config: BrowserConfig | None = None) -> AsyncIterator[Page]:
    """Create a new page within a browser context."""
    async with browser_context(config) as context:
        page = await context.new_page()
        try:
            yield page
        finally:
            await page.close()


@asynccontextmanager
async def ephemeral_browser(headless: bool = True) -> AsyncIterator[Browser]:
    """Create an ephemeral browser without persistent storage (for testing)."""
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=headless)
        try:
            yield browser
        finally:
            await browser.close()
