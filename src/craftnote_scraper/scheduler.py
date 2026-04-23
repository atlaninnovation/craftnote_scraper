import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Final

from aioclock import AioClock, Cron

from craftnote_scraper.api.client import CraftnoteClient
from craftnote_scraper.config import (
    DEFAULT_DB_PATH,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SYNC_LOOKBACK_HOURS,
    DEFAULT_SYNC_SCHEDULE,
    EXCLUDED_FOLDERS,
)
from craftnote_scraper.scraper.browser import BRAVE_EXECUTABLE_PATH, BrowserConfig, browser_context
from craftnote_scraper.scraper.downloader import download_all_project_files
from craftnote_scraper.storage.minio_adapter import MinIOAdapter
from craftnote_scraper.storage.models import DownloadedFile, FileType
from craftnote_scraper.storage.organizer import save_file
from craftnote_scraper.storage.tracker import DownloadTracker, SyncStatus, upload_pending_files

logger = logging.getLogger(__name__)

SYNC_SCHEDULE_ENV_VAR: Final[str] = "SYNC_SCHEDULE"
SYNC_LOOKBACK_HOURS_ENV_VAR: Final[str] = "SYNC_LOOKBACK_HOURS"
UPLOAD_SCHEDULE_ENV_VAR: Final[str] = "UPLOAD_SCHEDULE"
DEFAULT_TIMEZONE: Final[str] = "Europe/Berlin"
DEFAULT_UPLOAD_SCHEDULE: Final[str] = "0 2 * * *"  # 2 AM daily

MINIO_ENDPOINT_VAR: Final[str] = "MINIO_ENDPOINT"
MINIO_ACCESS_KEY_VAR: Final[str] = "MINIO_ACCESS_KEY"
MINIO_CREDENTIAL_VAR: Final[str] = "MINIO_SECRET_KEY"
MINIO_USE_SSL_VAR: Final[str] = "MINIO_USE_SSL"


def get_sync_schedule() -> str:
    return os.environ.get(SYNC_SCHEDULE_ENV_VAR, DEFAULT_SYNC_SCHEDULE)


def get_upload_schedule() -> str:
    return os.environ.get(UPLOAD_SCHEDULE_ENV_VAR, DEFAULT_UPLOAD_SCHEDULE)


def get_lookback_hours() -> int:
    value = os.environ.get(SYNC_LOOKBACK_HOURS_ENV_VAR)
    if value:
        return int(value)
    return DEFAULT_SYNC_LOOKBACK_HOURS


def create_minio_adapter_from_env() -> MinIOAdapter | None:
    endpoint = os.environ.get(MINIO_ENDPOINT_VAR)
    access_key = os.environ.get(MINIO_ACCESS_KEY_VAR)
    secret_key = os.environ.get(MINIO_CREDENTIAL_VAR)

    if not endpoint or not access_key or not secret_key:
        return None

    use_ssl = os.environ.get(MINIO_USE_SSL_VAR, "true").lower() == "true"
    return MinIOAdapter(
        endpoint=endpoint,
        access_key=access_key,
        secret_key=secret_key,
        secure=use_ssl,
    )


async def run_incremental_sync(
    output_dir: Path,
    tracker: DownloadTracker,
    lookback_hours: int,
    headless: bool = True,
    minio: MinIOAdapter | None = None,
) -> dict[str, int]:
    cutoff_time = datetime.now() - timedelta(hours=lookback_hours)
    logger.info("Starting incremental sync for projects modified since %s", cutoff_time)

    async with CraftnoteClient() as client:
        modified_projects = await client.get_modified_projects(cutoff_time, EXCLUDED_FOLDERS)

        parent_ids = {p.parent_project for p in modified_projects if p.parent_project}
        parent_map: dict[str, str] = {}
        for parent_id in parent_ids:
            try:
                parent = await client.get_project(parent_id)
                parent_map[parent_id] = parent.name
            except Exception:
                logger.debug("Could not fetch parent project %s", parent_id)

    if not modified_projects:
        logger.info("No projects modified since cutoff time")
        return {"projects_synced": 0, "files_downloaded": 0, "files_skipped": 0, "errors": 0}

    logger.info("Found %d modified projects", len(modified_projects))

    total_downloaded = 0
    total_skipped = 0
    total_errors = 0
    projects_synced = 0

    config = BrowserConfig(headless=headless, executable_path=BRAVE_EXECUTABLE_PATH)
    async with browser_context(config) as context:
        page = await context.new_page()

        for project in modified_projects:
            wind_farm = project.name
            if project.parent_project and project.parent_project in parent_map:
                wind_farm = parent_map[project.parent_project]
            turbine = project.name

            logger.info("Syncing project: %s / %s", wind_farm, turbine)
            project_files_downloaded = 0
            sync_status = SyncStatus.SUCCESS

            try:
                project_dir = output_dir / wind_farm / turbine
                results = await download_all_project_files(
                    page=page,
                    project_id=project.id,
                    download_dir=project_dir,
                )

                for result in results:
                    file_id = f"{project.id}_{result.metadata.filename}"

                    if tracker.is_already_downloaded(file_id):
                        total_skipped += 1
                        continue

                    final_path, checksum = save_file(
                        content=result.saved_path.read_bytes(),
                        wind_farm=wind_farm,
                        turbine=turbine,
                        filename=result.metadata.filename,
                        base_dir=output_dir,
                    )

                    downloaded_file = DownloadedFile(
                        file_id=file_id,
                        filename=result.metadata.filename,
                        file_type=FileType.from_filename(result.metadata.filename),
                        downloaded_at=datetime.now(),
                        path=final_path,
                        checksum=checksum,
                        wind_farm=wind_farm,
                        turbine=turbine,
                    )
                    tracker.record_download(downloaded_file)
                    total_downloaded += 1
                    project_files_downloaded += 1

                    if minio:
                        upload_result = minio.upload_file(
                            file_path=final_path,
                            wind_farm=wind_farm,
                            turbine_name=turbine,
                            original_filename=result.metadata.filename,
                            craftnote_project_id=project.id,
                        )
                        if upload_result.uploaded:
                            tracker.update_minio_upload(
                                file_id=file_id,
                                object_key=upload_result.object_key,
                                uploaded_at=datetime.now(),
                            )

                projects_synced += 1

            except Exception:
                total_errors += 1
                sync_status = SyncStatus.FAILED
                logger.exception("Error syncing project %s", turbine)

            last_edited_at = None
            if project.last_edited_date:
                last_edited_at = datetime.fromtimestamp(project.last_edited_date)

            tracker.record_project_sync(
                project_id=project.id,
                project_name=turbine,
                wind_farm=wind_farm,
                last_edited_at=last_edited_at,
                files_downloaded=project_files_downloaded,
                sync_status=sync_status,
            )

    stats = {
        "projects_synced": projects_synced,
        "files_downloaded": total_downloaded,
        "files_skipped": total_skipped,
        "errors": total_errors,
    }
    logger.info("Sync complete: %s", stats)
    return stats


def create_scheduler(
    output_dir: Path | None = None,
    db_path: Path | None = None,
    headless: bool = True,
    enable_minio: bool = False,
) -> AioClock:
    resolved_output_dir = output_dir or Path(DEFAULT_OUTPUT_DIR)
    resolved_db_path = db_path or Path(DEFAULT_DB_PATH)
    tracker = DownloadTracker(resolved_db_path)
    minio = create_minio_adapter_from_env() if enable_minio else None

    schedule = get_sync_schedule()
    lookback_hours = get_lookback_hours()
    upload_schedule = get_upload_schedule()

    clock = AioClock()

    @clock.task(trigger=Cron(cron=schedule, tz=DEFAULT_TIMEZONE))
    async def daily_sync() -> None:
        logger.info("Scheduled sync triggered")
        await run_incremental_sync(
            output_dir=resolved_output_dir,
            tracker=tracker,
            lookback_hours=lookback_hours,
            headless=headless,
            minio=minio,
        )

    @clock.task(trigger=Cron(cron=upload_schedule, tz=DEFAULT_TIMEZONE))
    async def daily_upload() -> None:
        if not minio:
            logger.debug("MinIO not configured, skipping upload task")
            return
        logger.info("Scheduled upload triggered")
        stats = await upload_pending_files(tracker, minio)
        logger.info("Upload complete: %s", stats)

    return clock


async def run_daemon(
    output_dir: Path | None = None,
    db_path: Path | None = None,
    headless: bool = True,
    enable_minio: bool = False,
) -> None:
    schedule = get_sync_schedule()
    logger.info("Starting daemon with schedule: %s", schedule)

    clock = create_scheduler(
        output_dir=output_dir,
        db_path=db_path,
        headless=headless,
        enable_minio=enable_minio,
    )

    await clock.serve()
