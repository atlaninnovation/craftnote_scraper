import logging
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Final

from playwright.async_api import Download, ElementHandle, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from craftnote_scraper.retry import RetryConfig, retry_async
from craftnote_scraper.scraper.exceptions import ChatNavigationError, DownloadError
from craftnote_scraper.scraper.login import CRAFTNOTE_APP_URL, ensure_logged_in

logger = logging.getLogger(__name__)


class DownloadableFileType(StrEnum):
    PDF = ".pdf"
    XLSX = ".xlsx"
    XLS = ".xls"


class ChatSelector(StrEnum):
    CHAT_MESSAGE = "app-chat-message"
    MESSAGE_CONTENT = ".message-content"
    PDF_HOLDER = ".pdf-holder, .document.pointer.thumb"
    DOCUMENT_FOOTER = ".document-footer"
    PDF_FILE_NAME = ".pdf-file-name"
    FILE_NAME_IN_MODAL = ".file-name"
    DOWNLOAD_ICON = 'em.material-icons.pointer:has-text("file_download")'
    DOWNLOAD_DIV = ".download"
    MODAL_CONTAINER = ".cdk-overlay-pane, .mat-dialog-container"
    MODAL_CLOSE = 'em.material-icons:has-text("close")'
    MESSAGE_SENDER = ".chat-message-header, .sender, .author"
    MESSAGE_TIMESTAMP = ".message-date, time, [class*='time']"


PAGE_LOAD_TIMEOUT_MS: Final[int] = 15_000
CHAT_LOAD_TIMEOUT_MS: Final[int] = 10_000
MODAL_TIMEOUT_MS: Final[int] = 5_000
DOWNLOAD_TIMEOUT_MS: Final[int] = 60_000
SCROLL_DELAY_MS: Final[int] = 500
RATE_LIMIT_DELAY_SECONDS: Final[float] = 1.0
MAX_SCROLL_ATTEMPTS: Final[int] = 50
DEFAULT_MAX_RETRIES: Final[int] = 3
PROJECT_URL_TEMPLATE: Final[str] = f"{CRAFTNOTE_APP_URL}/projects/{{project_id}}"

RETRYABLE_DOWNLOAD_EXCEPTIONS: tuple[type[Exception], ...] = (
    PlaywrightTimeoutError,
    DownloadError,
)


@dataclass(frozen=True)
class FileMetadata:
    filename: str
    file_type: DownloadableFileType
    uploaded_at: datetime | None = None
    uploader_name: str | None = None


@dataclass(frozen=True)
class DownloadResult:
    metadata: FileMetadata
    saved_path: Path
    original_url: str | None = None


def _is_downloadable_file(filename: str) -> bool:
    filename_lower = filename.lower()
    return any(filename_lower.endswith(ft.value) for ft in DownloadableFileType)


def _get_file_type(filename: str) -> DownloadableFileType:
    filename_lower = filename.lower()
    for file_type in DownloadableFileType:
        if filename_lower.endswith(file_type.value):
            return file_type
    raise ValueError(f"Unsupported file type: {filename}")


async def navigate_to_project_chat(page: Page, project_id: str) -> None:
    """
    Navigate to a project's chat view.

    The chat is displayed directly on the project page in Craftnote.

    Raises:
        ChatNavigationError: If navigation fails or chat doesn't load.
    """
    await ensure_logged_in(page)

    project_url = PROJECT_URL_TEMPLATE.format(project_id=project_id)
    try:
        await page.goto(project_url, timeout=PAGE_LOAD_TIMEOUT_MS)
    except PlaywrightTimeoutError as e:
        raise ChatNavigationError(f"Failed to load project page: {project_id}") from e

    try:
        await page.wait_for_selector(ChatSelector.CHAT_MESSAGE.value, timeout=CHAT_LOAD_TIMEOUT_MS)
    except PlaywrightTimeoutError as e:
        raise ChatNavigationError(f"Chat messages did not load for project: {project_id}") from e


async def _scroll_to_load_all_messages(page: Page) -> int:
    """Scroll through chat to load all messages with lazy loading."""
    scroll_container = await page.query_selector(ChatSelector.MESSAGE_CONTENT.value)
    if not scroll_container:
        messages = await page.query_selector_all(ChatSelector.CHAT_MESSAGE.value)
        return len(messages)

    previous_message_count = 0
    scroll_attempts = 0

    while scroll_attempts < MAX_SCROLL_ATTEMPTS:
        messages = await page.query_selector_all(ChatSelector.CHAT_MESSAGE.value)
        current_message_count = len(messages)

        if current_message_count == previous_message_count:
            break

        previous_message_count = current_message_count
        await scroll_container.evaluate("el => el.scrollTop = 0")
        await page.wait_for_timeout(SCROLL_DELAY_MS)
        scroll_attempts += 1

    return previous_message_count


async def _get_filename_from_element(file_element: ElementHandle) -> str | None:
    """Extract filename from a file holder element."""
    parent = await file_element.evaluate_handle("el => el.parentElement")
    parent_el = parent.as_element()
    if not parent_el:
        return None

    filename_el = await parent_el.query_selector(ChatSelector.PDF_FILE_NAME.value)
    if not filename_el:
        filename_el = await parent_el.query_selector(ChatSelector.DOCUMENT_FOOTER.value)

    if filename_el:
        text = await filename_el.text_content()
        if text:
            return text.strip()
    return None


async def _get_message_metadata(
    file_element: ElementHandle,
) -> tuple[datetime | None, str | None]:
    """Extract timestamp and sender from the parent message element."""
    message = await file_element.evaluate_handle("el => el.closest('app-chat-message')")
    message_el = message.as_element()
    if not message_el:
        return None, None

    uploaded_at: datetime | None = None
    uploader_name: str | None = None

    timestamp_el = await message_el.query_selector(ChatSelector.MESSAGE_TIMESTAMP.value)
    if timestamp_el:
        timestamp_text = await timestamp_el.text_content()
        if timestamp_text:
            uploaded_at = _parse_timestamp(timestamp_text)

    sender_el = await message_el.query_selector(ChatSelector.MESSAGE_SENDER.value)
    if sender_el:
        sender_text = await sender_el.text_content()
        if sender_text:
            uploader_name = sender_text.strip()

    return uploaded_at, uploader_name


def _parse_timestamp(timestamp_text: str) -> datetime | None:
    """Parse timestamp from various formats used by Craftnote."""
    formats = [
        "%d %b %Y",
        "%d.%m.%Y, %H:%M",
        "%d.%m.%Y %H:%M",
        "%Y-%m-%d %H:%M",
        "%d/%m/%Y %H:%M",
        "%H:%M",
        "%Y-%m-%dT%H:%M:%S",
    ]
    timestamp_text = timestamp_text.strip()
    for fmt in formats:
        try:
            return datetime.strptime(timestamp_text, fmt)
        except ValueError:
            continue
    return None


async def find_files_in_chat(
    page: Page,
) -> list[tuple[ElementHandle, FileMetadata]]:
    """
    Locate all downloadable files (PDF, XLSX, XLS) in the chat.

    Returns:
        List of tuples containing the file element handle and its metadata.
    """
    await _scroll_to_load_all_messages(page)

    file_elements = await page.query_selector_all(ChatSelector.PDF_HOLDER.value)
    results: list[tuple[ElementHandle, FileMetadata]] = []

    for element in file_elements:
        filename = await _get_filename_from_element(element)
        if not filename or not _is_downloadable_file(filename):
            continue

        uploaded_at, uploader_name = await _get_message_metadata(element)

        metadata = FileMetadata(
            filename=filename,
            file_type=_get_file_type(filename),
            uploaded_at=uploaded_at,
            uploader_name=uploader_name,
        )
        results.append((element, metadata))

    return results


async def _close_modal_if_open(page: Page) -> None:
    """Close any open modal dialog."""
    close_btn = await page.query_selector(ChatSelector.MODAL_CLOSE.value)
    if close_btn:
        try:
            await close_btn.click()
            await page.wait_for_timeout(500)
        except PlaywrightTimeoutError:
            pass


async def _download_via_modal(page: Page, metadata: FileMetadata) -> Download:
    """Download file by clicking download icon in the modal (used for PDFs)."""
    download_icon = await page.query_selector(ChatSelector.DOWNLOAD_ICON.value)
    if not download_icon:
        download_div = await page.query_selector(ChatSelector.DOWNLOAD_DIV.value)
        if download_div:
            download_icon = await download_div.query_selector("em.material-icons")

    if not download_icon:
        raise DownloadError(f"Download button not found for file: {metadata.filename}")

    async with page.expect_download(timeout=DOWNLOAD_TIMEOUT_MS) as download_info:
        await download_icon.click()

    return await download_info.value


async def _perform_download(
    page: Page,
    file_element: ElementHandle,
    metadata: FileMetadata,
    download_dir: Path,
) -> DownloadResult:
    """Internal download logic without retry wrapper."""
    is_pdf = metadata.file_type == DownloadableFileType.PDF

    try:
        if is_pdf:
            await file_element.click()
            await page.wait_for_timeout(MODAL_TIMEOUT_MS)
            download = await _download_via_modal(page, metadata)
        else:
            async with page.expect_download(timeout=DOWNLOAD_TIMEOUT_MS) as download_info:
                await file_element.click()
            download = await download_info.value

        suggested_filename = download.suggested_filename or metadata.filename
        save_path = download_dir / suggested_filename

        await download.save_as(save_path)

        await _close_modal_if_open(page)

        return DownloadResult(
            metadata=metadata,
            saved_path=save_path,
            original_url=download.url,
        )
    except PlaywrightTimeoutError as e:
        await _close_modal_if_open(page)
        raise DownloadError(f"Download timed out for file: {metadata.filename}") from e
    except DownloadError:
        await _close_modal_if_open(page)
        raise
    except Exception as e:
        await _close_modal_if_open(page)
        raise DownloadError(f"Failed to download file: {metadata.filename}") from e


async def download_file(
    page: Page,
    file_element: ElementHandle,
    metadata: FileMetadata,
    download_dir: Path,
    retry_config: RetryConfig | None = None,
) -> DownloadResult:
    """
    Download a file from a chat attachment element with retry support.

    PDF files open a preview modal with a download icon.
    XLSX/XLS files download directly when clicked.

    Raises:
        DownloadError: If download fails after all retries.
    """
    download_dir.mkdir(parents=True, exist_ok=True)
    config = retry_config or RetryConfig(max_retries=DEFAULT_MAX_RETRIES)

    return await retry_async(
        lambda: _perform_download(page, file_element, metadata, download_dir),
        RETRYABLE_DOWNLOAD_EXCEPTIONS,
        config,
        operation_name=f"download {metadata.filename}",
    )


async def download_all_project_files(
    page: Page,
    project_id: str,
    download_dir: Path,
    rate_limit_delay: float = RATE_LIMIT_DELAY_SECONDS,
) -> list[DownloadResult]:
    """
    Navigate to a project chat and download all PDF/XLSX/XLS files.

    Args:
        page: Playwright page instance.
        project_id: Craftnote project ID.
        download_dir: Directory to save downloaded files.
        rate_limit_delay: Delay between downloads in seconds.

    Returns:
        List of download results with metadata and file paths.

    Raises:
        ChatNavigationError: If navigation to chat fails.
        DownloadError: If any download fails.
    """
    await navigate_to_project_chat(page, project_id)

    files = await find_files_in_chat(page)
    results: list[DownloadResult] = []

    for file_element, metadata in files:
        result = await download_file(page, file_element, metadata, download_dir)
        results.append(result)

        if rate_limit_delay > 0:
            await page.wait_for_timeout(int(rate_limit_delay * 1000))

    return results


@dataclass(frozen=True)
class TurbineDownloadResult:
    turbine_name: str
    project_id: str
    files: list[DownloadResult]
    error: str | None = None


@dataclass(frozen=True)
class WindFarmDownloadResult:
    wind_farm_name: str
    turbine_results: list[TurbineDownloadResult]
    total_files: int
    total_errors: int


async def download_wind_farm_files(
    page: Page,
    wind_farm_name: str,
    turbines: list[tuple[str, str]],
    base_download_dir: Path,
    rate_limit_delay: float = RATE_LIMIT_DELAY_SECONDS,
) -> WindFarmDownloadResult:
    """
    Download all files for a wind farm's turbines.

    Creates a directory structure: base_dir/wind_farm_name/turbine_name/

    Args:
        page: Playwright page instance.
        wind_farm_name: Name of the wind farm (used for directory).
        turbines: List of (turbine_name, project_id) tuples.
        base_download_dir: Base directory for downloads.
        rate_limit_delay: Delay between downloads in seconds.

    Returns:
        WindFarmDownloadResult with results for each turbine.
    """
    turbine_results: list[TurbineDownloadResult] = []
    total_files = 0
    total_errors = 0

    wind_farm_dir = base_download_dir / _sanitize_filename(wind_farm_name)

    for turbine_name, project_id in turbines:
        if not project_id:
            turbine_results.append(
                TurbineDownloadResult(
                    turbine_name=turbine_name,
                    project_id="",
                    files=[],
                    error="No project ID",
                )
            )
            total_errors += 1
            continue

        turbine_dir = wind_farm_dir / _sanitize_filename(turbine_name)

        try:
            files = await download_all_project_files(
                page, project_id, turbine_dir, rate_limit_delay
            )
            turbine_results.append(
                TurbineDownloadResult(
                    turbine_name=turbine_name,
                    project_id=project_id,
                    files=files,
                )
            )
            total_files += len(files)
        except (ChatNavigationError, DownloadError) as e:
            turbine_results.append(
                TurbineDownloadResult(
                    turbine_name=turbine_name,
                    project_id=project_id,
                    files=[],
                    error=str(e),
                )
            )
            total_errors += 1

    return WindFarmDownloadResult(
        wind_farm_name=wind_farm_name,
        turbine_results=turbine_results,
        total_files=total_files,
        total_errors=total_errors,
    )


def _sanitize_filename(name: str) -> str:
    """Remove or replace characters that are invalid in filenames."""
    invalid_chars = '<>:"/\\|?*'
    result = name
    for char in invalid_chars:
        result = result.replace(char, "_")
    return result.strip()
