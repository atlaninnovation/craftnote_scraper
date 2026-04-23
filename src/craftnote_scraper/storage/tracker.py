import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Final

from craftnote_scraper.storage.models import DownloadedFile, FileType

if TYPE_CHECKING:
    from craftnote_scraper.storage.minio_adapter import MinIOAdapter

DEFAULT_DB_PATH: Final[str] = "downloads.db"

CREATE_TABLE_SQL: Final[str] = """
CREATE TABLE IF NOT EXISTS downloaded_files (
    file_id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    file_type TEXT NOT NULL,
    downloaded_at TEXT NOT NULL,
    path TEXT NOT NULL,
    checksum TEXT NOT NULL,
    wind_farm TEXT NOT NULL,
    turbine TEXT NOT NULL,
    minio_object_key TEXT,
    minio_uploaded_at TEXT
)
"""

CREATE_PROJECT_SYNC_TABLE_SQL: Final[str] = """
CREATE TABLE IF NOT EXISTS project_sync_status (
    project_id TEXT PRIMARY KEY,
    project_name TEXT NOT NULL,
    wind_farm TEXT NOT NULL,
    last_synced_at TEXT NOT NULL,
    last_edited_at TEXT,
    files_downloaded INTEGER DEFAULT 0,
    sync_status TEXT NOT NULL DEFAULT 'success'
)
"""

CREATE_INDEX_CHECKSUM_SQL: Final[str] = """
CREATE INDEX IF NOT EXISTS idx_checksum ON downloaded_files (checksum)
"""

CREATE_INDEX_WIND_FARM_SQL: Final[str] = """
CREATE INDEX IF NOT EXISTS idx_wind_farm ON downloaded_files (wind_farm)
"""

CREATE_INDEX_PROJECT_SYNC_WIND_FARM_SQL: Final[str] = """
CREATE INDEX IF NOT EXISTS idx_project_sync_wind_farm ON project_sync_status (wind_farm)
"""

ADD_MINIO_OBJECT_KEY_COLUMN_SQL: Final[str] = """
ALTER TABLE downloaded_files ADD COLUMN minio_object_key TEXT
"""

ADD_MINIO_UPLOADED_AT_COLUMN_SQL: Final[str] = """
ALTER TABLE downloaded_files ADD COLUMN minio_uploaded_at TEXT
"""

INSERT_SQL: Final[str] = """
INSERT OR REPLACE INTO downloaded_files
    (file_id, filename, file_type, downloaded_at, path, checksum, wind_farm, turbine,
     minio_object_key, minio_uploaded_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

INSERT_PROJECT_SYNC_SQL: Final[str] = """
INSERT OR REPLACE INTO project_sync_status
    (project_id, project_name, wind_farm, last_synced_at,
     last_edited_at, files_downloaded, sync_status)
VALUES (?, ?, ?, ?, ?, ?, ?)
"""

SELECT_BY_ID_SQL: Final[str] = """
SELECT file_id, filename, file_type, downloaded_at, path, checksum, wind_farm, turbine,
       minio_object_key, minio_uploaded_at
FROM downloaded_files WHERE file_id = ?
"""

SELECT_BY_CHECKSUM_SQL: Final[str] = """
SELECT file_id, filename, file_type, downloaded_at, path, checksum, wind_farm, turbine,
       minio_object_key, minio_uploaded_at
FROM downloaded_files WHERE checksum = ?
"""

SELECT_BY_WIND_FARM_SQL: Final[str] = """
SELECT file_id, filename, file_type, downloaded_at, path, checksum, wind_farm, turbine,
       minio_object_key, minio_uploaded_at
FROM downloaded_files WHERE wind_farm = ?
ORDER BY downloaded_at DESC
"""

SELECT_ALL_SQL: Final[str] = """
SELECT file_id, filename, file_type, downloaded_at, path, checksum, wind_farm, turbine,
       minio_object_key, minio_uploaded_at
FROM downloaded_files ORDER BY downloaded_at DESC
"""

UPDATE_MINIO_SQL: Final[str] = """
UPDATE downloaded_files
SET minio_object_key = ?, minio_uploaded_at = ?
WHERE file_id = ?
"""

SELECT_PROJECT_SYNC_BY_ID_SQL: Final[str] = """
SELECT project_id, project_name, wind_farm, last_synced_at,
       last_edited_at, files_downloaded, sync_status
FROM project_sync_status WHERE project_id = ?
"""

SELECT_LAST_SYNC_TIME_SQL: Final[str] = """
SELECT MAX(last_synced_at) FROM project_sync_status
"""

SELECT_ALL_PROJECT_SYNCS_SQL: Final[str] = """
SELECT project_id, project_name, wind_farm, last_synced_at,
       last_edited_at, files_downloaded, sync_status
FROM project_sync_status ORDER BY last_synced_at DESC
"""


class SyncStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"


@dataclass(frozen=True)
class ProjectSyncRecord:
    project_id: str
    project_name: str
    wind_farm: str
    last_synced_at: datetime
    last_edited_at: datetime | None
    files_downloaded: int
    sync_status: SyncStatus


def _row_to_downloaded_file(
    row: tuple[str, str, str, str, str, str, str, str, str | None, str | None],
) -> DownloadedFile:
    (
        file_id,
        filename,
        file_type,
        downloaded_at,
        path,
        checksum,
        wind_farm,
        turbine,
        minio_object_key,
        minio_uploaded_at,
    ) = row
    return DownloadedFile(
        file_id=file_id,
        filename=filename,
        file_type=FileType(file_type),
        downloaded_at=datetime.fromisoformat(downloaded_at),
        path=Path(path),
        checksum=checksum,
        wind_farm=wind_farm,
        turbine=turbine,
        minio_object_key=minio_object_key,
        minio_uploaded_at=(
            datetime.fromisoformat(minio_uploaded_at) if minio_uploaded_at else None
        ),
    )


def _row_to_project_sync_record(
    row: tuple[str, str, str, str, str | None, int, str],
) -> ProjectSyncRecord:
    (
        project_id,
        project_name,
        wind_farm,
        last_synced_at,
        last_edited_at,
        files_downloaded,
        sync_status,
    ) = row
    return ProjectSyncRecord(
        project_id=project_id,
        project_name=project_name,
        wind_farm=wind_farm,
        last_synced_at=datetime.fromisoformat(last_synced_at),
        last_edited_at=datetime.fromisoformat(last_edited_at) if last_edited_at else None,
        files_downloaded=files_downloaded,
        sync_status=SyncStatus(sync_status),
    )


class DownloadTracker:
    def __init__(self, db_path: Path | None = None):
        self._db_path = db_path or Path(DEFAULT_DB_PATH)
        self._init_db()

    def _init_db(self) -> None:
        with self._connection() as conn:
            conn.execute(CREATE_TABLE_SQL)
            conn.execute(CREATE_PROJECT_SYNC_TABLE_SQL)
            conn.execute(CREATE_INDEX_CHECKSUM_SQL)
            conn.execute(CREATE_INDEX_WIND_FARM_SQL)
            conn.execute(CREATE_INDEX_PROJECT_SYNC_WIND_FARM_SQL)
            self._migrate_add_minio_columns(conn)

    def _migrate_add_minio_columns(self, conn: sqlite3.Connection) -> None:
        cursor = conn.execute("PRAGMA table_info(downloaded_files)")
        columns = {row[1] for row in cursor.fetchall()}

        if "minio_object_key" not in columns:
            conn.execute(ADD_MINIO_OBJECT_KEY_COLUMN_SQL)
        if "minio_uploaded_at" not in columns:
            conn.execute(ADD_MINIO_UPLOADED_AT_COLUMN_SQL)

    @contextmanager
    def _connection(self):
        conn = sqlite3.connect(self._db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def is_already_downloaded(self, file_id: str) -> bool:
        with self._connection() as conn:
            cursor = conn.execute(SELECT_BY_ID_SQL, (file_id,))
            return cursor.fetchone() is not None

    def is_duplicate_checksum(self, checksum: str) -> bool:
        with self._connection() as conn:
            cursor = conn.execute(SELECT_BY_CHECKSUM_SQL, (checksum,))
            return cursor.fetchone() is not None

    def record_download(self, downloaded_file: DownloadedFile) -> None:
        with self._connection() as conn:
            conn.execute(
                INSERT_SQL,
                (
                    downloaded_file.file_id,
                    downloaded_file.filename,
                    downloaded_file.file_type.value,
                    downloaded_file.downloaded_at.isoformat(),
                    str(downloaded_file.path),
                    downloaded_file.checksum,
                    downloaded_file.wind_farm,
                    downloaded_file.turbine,
                    downloaded_file.minio_object_key,
                    (
                        downloaded_file.minio_uploaded_at.isoformat()
                        if downloaded_file.minio_uploaded_at
                        else None
                    ),
                ),
            )

    def update_minio_upload(self, file_id: str, object_key: str, uploaded_at: datetime) -> None:
        with self._connection() as conn:
            conn.execute(UPDATE_MINIO_SQL, (object_key, uploaded_at.isoformat(), file_id))

    def get_download(self, file_id: str) -> DownloadedFile | None:
        with self._connection() as conn:
            cursor = conn.execute(SELECT_BY_ID_SQL, (file_id,))
            row = cursor.fetchone()
            if row is None:
                return None
            return _row_to_downloaded_file(row)

    def get_download_history(self, wind_farm: str | None = None) -> list[DownloadedFile]:
        with self._connection() as conn:
            if wind_farm is not None:
                cursor = conn.execute(SELECT_BY_WIND_FARM_SQL, (wind_farm,))
            else:
                cursor = conn.execute(SELECT_ALL_SQL)
            return [_row_to_downloaded_file(row) for row in cursor.fetchall()]

    def record_project_sync(
        self,
        project_id: str,
        project_name: str,
        wind_farm: str,
        last_edited_at: datetime | None,
        files_downloaded: int,
        sync_status: SyncStatus = SyncStatus.SUCCESS,
    ) -> None:
        with self._connection() as conn:
            conn.execute(
                INSERT_PROJECT_SYNC_SQL,
                (
                    project_id,
                    project_name,
                    wind_farm,
                    datetime.now().isoformat(),
                    last_edited_at.isoformat() if last_edited_at else None,
                    files_downloaded,
                    sync_status.value,
                ),
            )

    def get_project_sync(self, project_id: str) -> ProjectSyncRecord | None:
        with self._connection() as conn:
            cursor = conn.execute(SELECT_PROJECT_SYNC_BY_ID_SQL, (project_id,))
            row = cursor.fetchone()
            if row is None:
                return None
            return _row_to_project_sync_record(row)

    def get_last_sync_time(self) -> datetime | None:
        with self._connection() as conn:
            cursor = conn.execute(SELECT_LAST_SYNC_TIME_SQL)
            row = cursor.fetchone()
            if row is None or row[0] is None:
                return None
            return datetime.fromisoformat(row[0])

    def get_all_project_syncs(self) -> list[ProjectSyncRecord]:
        with self._connection() as conn:
            cursor = conn.execute(SELECT_ALL_PROJECT_SYNCS_SQL)
            return [_row_to_project_sync_record(row) for row in cursor.fetchall()]

    def get_pending_uploads(self) -> list[DownloadedFile]:
        """Get all files that have been downloaded but not yet uploaded to MinIO."""
        with self._connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM downloaded_files WHERE minio_uploaded_at IS NULL "
                "ORDER BY downloaded_at"
            )
            return [_row_to_downloaded_file(row) for row in cursor.fetchall()]


async def upload_pending_files(
    tracker: DownloadTracker,
    minio: "MinIOAdapter",
) -> dict[str, int]:
    """
    Upload all pending files to MinIO.

    Returns a dict with keys: uploaded, skipped, errors
    """
    pending_files = tracker.get_pending_uploads()

    if not pending_files:
        return {"uploaded": 0, "skipped": 0, "errors": 0}

    total_uploaded = 0
    total_skipped = 0
    total_errors = 0

    for file in pending_files:
        file_path = Path(file.path)

        if not file_path.exists():
            total_errors += 1
            continue

        try:
            upload_result = minio.upload_file(
                file_path=file_path,
                wind_farm=file.wind_farm,
                turbine_name=file.turbine,
                original_filename=file.filename,
                craftnote_project_id="unknown",
            )

            if upload_result.uploaded:
                tracker.update_minio_upload(
                    file_id=file.file_id,
                    object_key=upload_result.object_key,
                    uploaded_at=datetime.now(),
                )
                total_uploaded += 1
            else:
                total_skipped += 1
        except Exception:
            total_errors += 1

    return {
        "uploaded": total_uploaded,
        "skipped": total_skipped,
        "errors": total_errors,
    }
