import contextlib
import os
from enum import StrEnum
from pathlib import Path
from typing import Final

from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from craftnote_scraper.scraper.exceptions import (
    LoginError,
    RateLimitedError,
    SessionExpiredError,
    TwoFactorRequiredError,
)

CRAFTNOTE_APP_URL: Final[str] = "https://app.mycraftnote.de"
LOGIN_TIMEOUT_MS: Final[int] = 30_000
NAVIGATION_TIMEOUT_MS: Final[int] = 10_000


_CREDENTIAL_INPUT_TYPE: Final[str] = "password"


class LoginSelector(StrEnum):
    EMAIL_INPUT = 'input[name="email"]'
    SUBMIT_BUTTON = 'button[type="submit"]'
    TWO_FACTOR_INPUT = 'input[name="code"]'
    ERROR_MESSAGE = '[class*="error"], [class*="alert-danger"]'


class ModalSelector(StrEnum):
    REMIND_ME_LATER = '[data-cy="notifications-remind-later"]'
    CLOSE_BUTTON = 'button:has-text("close")'


def _credential_input_selector() -> str:
    return f'input[type="{_CREDENTIAL_INPUT_TYPE}"]'


class DashboardSelector(StrEnum):
    PROJECT_LIST = '[class*="project"], [class*="dashboard"]'
    USER_MENU = '[class*="user"], [class*="avatar"], [class*="profile"]'


def _load_credentials_from_env(secrets_path: Path | None = None) -> tuple[str, str]:
    email = os.environ.get("CRAFTNOTE_EMAIL")
    password = os.environ.get("CRAFTNOTE_PASSWORD")

    if email and password:
        return email, password

    path = secrets_path or Path("secrets.env")
    if path.exists():
        with path.open() as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip()
                    if key == "CRAFTNOTE_EMAIL" and not email:
                        email = value
                    elif key == "CRAFTNOTE_PASSWORD" and not password:
                        password = value

    if not email or not password:
        raise LoginError(
            "Missing CRAFTNOTE_EMAIL or CRAFTNOTE_PASSWORD in environment or secrets.env"
        )

    return email, password


async def is_logged_in(page: Page) -> bool:
    """Check if the current page indicates an authenticated session."""
    url = page.url

    if "login" in url or "signin" in url or "auth" in url:
        return False

    login_form = await page.query_selector(LoginSelector.EMAIL_INPUT.value)
    return not login_form


async def _detect_login_error(page: Page) -> str | None:
    """Detect and return any login error message displayed on the page."""
    try:
        error_element = await page.query_selector(LoginSelector.ERROR_MESSAGE.value)
        if error_element:
            return await error_element.text_content()
    except PlaywrightTimeoutError:
        pass
    return None


async def _check_for_two_factor(page: Page) -> bool:
    """Check if 2FA input is present on the page."""
    try:
        two_factor_input = await page.query_selector(LoginSelector.TWO_FACTOR_INPUT.value)
        return two_factor_input is not None
    except PlaywrightTimeoutError:
        return False


async def _check_for_rate_limit(page: Page) -> bool:
    """Check if the page indicates rate limiting."""
    content = await page.content()
    rate_limit_indicators = ["rate limit", "too many requests", "try again later", "429"]
    content_lower = content.lower()
    return any(indicator in content_lower for indicator in rate_limit_indicators)


MODAL_DISMISS_TIMEOUT_MS: Final[int] = 10_000


async def dismiss_modals(page: Page) -> None:
    """Dismiss any post-login modals like notification prompts."""
    for selector in ModalSelector:
        try:
            element = await page.wait_for_selector(
                selector.value, timeout=MODAL_DISMISS_TIMEOUT_MS, state="visible"
            )
            if element:
                await element.click()
                return
        except PlaywrightTimeoutError:
            continue


async def login(
    page: Page,
    email: str | None = None,
    password: str | None = None,
    secrets_path: Path | None = None,
) -> None:
    """
    Authenticate to Craftnote web app.

    Raises:
        LoginError: If login fails due to invalid credentials or other errors.
        TwoFactorRequiredError: If 2FA is required (needs manual intervention).
        RateLimitedError: If rate limited by the server.
    """
    if email is None or password is None:
        loaded_email, loaded_password = _load_credentials_from_env(secrets_path)
        email = email or loaded_email
        password = password or loaded_password

    await page.goto(CRAFTNOTE_APP_URL, timeout=NAVIGATION_TIMEOUT_MS)

    if await is_logged_in(page):
        await dismiss_modals(page)
        return

    try:
        await page.wait_for_selector(LoginSelector.EMAIL_INPUT.value, timeout=LOGIN_TIMEOUT_MS)
    except PlaywrightTimeoutError as e:
        raise LoginError("Login page did not load within timeout") from e

    await page.fill(LoginSelector.EMAIL_INPUT.value, email)
    await page.fill(_credential_input_selector(), password)
    await page.click(LoginSelector.SUBMIT_BUTTON.value)

    with contextlib.suppress(PlaywrightTimeoutError):
        await page.wait_for_url("**/projects**", timeout=LOGIN_TIMEOUT_MS)

    if await _check_for_rate_limit(page):
        raise RateLimitedError("Rate limited by Craftnote. Please try again later.")

    if await _check_for_two_factor(page):
        raise TwoFactorRequiredError(
            "Two-factor authentication required. Please complete manually."
        )

    error_message = await _detect_login_error(page)
    if error_message:
        raise LoginError(f"Login failed: {error_message}")

    if not await is_logged_in(page):
        raise LoginError("Login failed: unable to verify authenticated session")

    await dismiss_modals(page)


async def ensure_logged_in(
    page: Page,
    email: str | None = None,
    password: str | None = None,
    secrets_path: Path | None = None,
) -> None:
    """
    Ensure the session is authenticated, re-logging in if necessary.

    Raises:
        SessionExpiredError: If session expired and re-login failed.
        LoginError: If login fails.
        TwoFactorRequiredError: If 2FA is required.
        RateLimitedError: If rate limited.
    """
    if await is_logged_in(page):
        return

    try:
        await login(page, email, password, secrets_path)
    except LoginError as e:
        raise SessionExpiredError(f"Session expired and re-login failed: {e}") from e
