import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Final

from craftnote_scraper.storage.models import DownloadedFile, FileType

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
    turbine TEXT NOT NULL
)
"""

CREATE_INDEX_CHECKSUM_SQL: Final[str] = """
CREATE INDEX IF NOT EXISTS idx_checksum ON downloaded_files (checksum)
"""

CREATE_INDEX_WIND_FARM_SQL: Final[str] = """
CREATE INDEX IF NOT EXISTS idx_wind_farm ON downloaded_files (wind_farm)
"""

INSERT_SQL: Final[str] = """
INSERT OR REPLACE INTO downloaded_files
    (file_id, filename, file_type, downloaded_at, path, checksum, wind_farm, turbine)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""

SELECT_BY_ID_SQL: Final[str] = """
SELECT file_id, filename, file_type, downloaded_at, path, checksum, wind_farm, turbine
FROM downloaded_files WHERE file_id = ?
"""

SELECT_BY_CHECKSUM_SQL: Final[str] = """
SELECT file_id, filename, file_type, downloaded_at, path, checksum, wind_farm, turbine
FROM downloaded_files WHERE checksum = ?
"""

SELECT_BY_WIND_FARM_SQL: Final[str] = """
SELECT file_id, filename, file_type, downloaded_at, path, checksum, wind_farm, turbine
FROM downloaded_files WHERE wind_farm = ?
ORDER BY downloaded_at DESC
"""

SELECT_ALL_SQL: Final[str] = """
SELECT file_id, filename, file_type, downloaded_at, path, checksum, wind_farm, turbine
FROM downloaded_files ORDER BY downloaded_at DESC
"""


def _row_to_downloaded_file(row: tuple[str, str, str, str, str, str, str, str]) -> DownloadedFile:
    file_id, filename, file_type, downloaded_at, path, checksum, wind_farm, turbine = row
    return DownloadedFile(
        file_id=file_id,
        filename=filename,
        file_type=FileType(file_type),
        downloaded_at=datetime.fromisoformat(downloaded_at),
        path=Path(path),
        checksum=checksum,
        wind_farm=wind_farm,
        turbine=turbine,
    )


class DownloadTracker:
    def __init__(self, db_path: Path | None = None):
        self._db_path = db_path or Path(DEFAULT_DB_PATH)
        self._init_db()

    def _init_db(self) -> None:
        with self._connection() as conn:
            conn.execute(CREATE_TABLE_SQL)
            conn.execute(CREATE_INDEX_CHECKSUM_SQL)
            conn.execute(CREATE_INDEX_WIND_FARM_SQL)

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
                ),
            )

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
