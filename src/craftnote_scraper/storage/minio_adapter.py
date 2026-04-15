import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from io import BytesIO
from pathlib import Path
from typing import Final

from minio import Minio
from minio.error import S3Error
from slugify import slugify

from craftnote_scraper.storage.organizer import compute_checksum

logger = logging.getLogger(__name__)

BUCKET_NAME: Final[str] = "service-reports"
INBOX_PREFIX: Final[str] = "inbox/"
ARCHIVE_PREFIX: Final[str] = "archive/"
META_SUFFIX: Final[str] = ".meta.json"
CHECKSUM_METADATA_KEY: Final[str] = "x-amz-meta-checksum-sha256"


class ContentType(Enum):
    PDF = "application/pdf"
    XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    XLS = "application/vnd.ms-excel"
    OCTET_STREAM = "application/octet-stream"
    JSON = "application/json"

    @classmethod
    def from_extension(cls, extension: str) -> "ContentType":
        extension_map = {
            ".pdf": cls.PDF,
            ".xlsx": cls.XLSX,
            ".xls": cls.XLS,
        }
        return extension_map.get(extension.lower(), cls.OCTET_STREAM)


@dataclass(frozen=True)
class UploadResult:
    object_key: str
    checksum: str
    uploaded: bool


class MinIOAdapter:
    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        secure: bool = True,
    ):
        self._client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )
        self._ensure_bucket_exists()
        self._checksum_cache: set[str] | None = None

    def _ensure_bucket_exists(self) -> None:
        if not self._client.bucket_exists(BUCKET_NAME):
            self._client.make_bucket(BUCKET_NAME)

    def _load_checksum_cache(self) -> set[str]:
        if self._checksum_cache is not None:
            return self._checksum_cache

        logger.info("Loading checksum cache from MinIO (one-time operation)")
        checksums: set[str] = set()

        for prefix in (INBOX_PREFIX, ARCHIVE_PREFIX):
            for obj in self._client.list_objects(BUCKET_NAME, prefix=prefix, recursive=True):
                if obj.object_name.endswith(META_SUFFIX):
                    continue
                try:
                    stat = self._client.stat_object(BUCKET_NAME, obj.object_name)
                    if stat.metadata:
                        checksum = stat.metadata.get(CHECKSUM_METADATA_KEY)
                        if checksum:
                            checksums.add(checksum)
                except S3Error as err:
                    logger.debug("Failed to stat object %s: %s", obj.object_name, err.code)

        self._checksum_cache = checksums
        logger.info("Loaded %d checksums into cache", len(checksums))
        return checksums

    def upload_file(
        self,
        file_path: Path,
        wind_farm: str,
        turbine_name: str,
        original_filename: str,
        craftnote_project_id: str,
    ) -> UploadResult:
        checksum = compute_checksum(file_path)

        if self._exists_by_checksum(checksum):
            return UploadResult(object_key="", checksum=checksum, uploaded=False)

        report_date = extract_date_from_filename(original_filename)
        object_key = self._build_object_key(wind_farm, turbine_name, report_date, original_filename)

        content_type = ContentType.from_extension(file_path.suffix)
        self._client.fput_object(
            BUCKET_NAME,
            object_key,
            str(file_path),
            content_type=content_type.value,
            metadata={"checksum-sha256": checksum},
        )

        self._upload_metadata_sidecar(
            object_key=object_key,
            original_filename=original_filename,
            wind_farm=wind_farm,
            turbine_name=turbine_name,
            checksum=checksum,
            file_size=file_path.stat().st_size,
            content_type=content_type,
            craftnote_project_id=craftnote_project_id,
        )

        self._checksum_cache_add(checksum)
        return UploadResult(object_key=object_key, checksum=checksum, uploaded=True)

    def _checksum_cache_add(self, checksum: str) -> None:
        if self._checksum_cache is not None:
            self._checksum_cache.add(checksum)

    def _upload_metadata_sidecar(
        self,
        object_key: str,
        original_filename: str,
        wind_farm: str,
        turbine_name: str,
        checksum: str,
        file_size: int,
        content_type: ContentType,
        craftnote_project_id: str,
    ) -> None:
        meta = {
            "source": "craftnote",
            "craftnote_project_id": craftnote_project_id,
            "original_filename": original_filename,
            "wind_farm": wind_farm,
            "turbine_name": turbine_name,
            "checksum_sha256": checksum,
            "uploaded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "uploaded_by": "craftnote_scraper",
            "file_size_bytes": file_size,
            "content_type": content_type.value,
        }
        meta_key = f"{object_key}{META_SUFFIX}"
        meta_bytes = json.dumps(meta, indent=2).encode()

        self._client.put_object(
            BUCKET_NAME,
            meta_key,
            BytesIO(meta_bytes),
            len(meta_bytes),
            content_type=ContentType.JSON.value,
        )

    def _build_object_key(
        self,
        wind_farm: str,
        turbine_name: str,
        report_date: str,
        filename: str,
    ) -> str:
        farm_slug = slugify(wind_farm, lowercase=True)
        turbine_slug = slugify(turbine_name, lowercase=True)
        filename_slug = slugify(Path(filename).stem, lowercase=True)
        ext = Path(filename).suffix.lower()
        return f"{INBOX_PREFIX}{farm_slug}/{turbine_slug}/{report_date}_{filename_slug}{ext}"

    def _exists_by_checksum(self, checksum: str) -> bool:
        checksums = self._load_checksum_cache()
        return checksum in checksums


DEFAULT_DATE: Final[str] = "unknown-date"

YYYYMMDD_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"[_\s]((?:19|20)\d{2})(\d{2})(\d{2})(?:[_\s]\d{6,}|[_\s][a-zA-Z]|\.[a-zA-Z]+$)"
)
YYYY_MM_DD_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"((?:19|20)\d{2})[.\-_/](\d{1,2})[.\-_/](\d{1,2})"
)
DDMMYY_COMPACT_PATTERN: Final[re.Pattern[str]] = re.compile(r"^(\d{2})(\d{2})(\d{2})\s")
DATE_PATTERN: Final[re.Pattern[str]] = re.compile(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})")
DATE_SPACE_PATTERN: Final[re.Pattern[str]] = re.compile(r"(\d{1,2})\s+(\d{1,2})\.(\d{4})")
YYYY_MM_PATTERN: Final[re.Pattern[str]] = re.compile(r"(\d{4})-(\d{2})_")


def _normalize_year(year: str) -> str:
    if len(year) == 2:
        return f"20{year}"
    return year


def _format_date(year: str, month: str, day: str) -> str:
    return f"{_normalize_year(year)}-{int(month):02d}-{int(day):02d}"


def extract_date_from_filename(filename: str) -> str:
    """
    Extract date from filename and return in YYYY-MM-DD format.

    Supports formats:
    - "Servicebericht Boddin 6.5.2025.pdf" -> "2025-05-06"
    - "Report 2025-05-06.pdf" -> "2025-05-06"
    - "2026_04_13_GE15560452.pdf" -> "2026-04-13"
    - "WEA4_12-05-2025.xlsx" -> "2025-05-12"
    - "230725 BA2.pdf" -> "2025-07-23" (DDMMYY compact at start)
    - "GE_15560445_20260324.pdf" -> "2026-03-24" (YYYYMMDD with underscores)
    - "2024-06_Sicherheitsprufung.pdf" -> "2024-06-01" (YYYY-MM only)
    - "Servicebericht 02 04.2026.pdf" -> "2026-04-02" (DD MM.YYYY)
    """
    if match := YYYYMMDD_PATTERN.search(filename):
        year, month, day = match.groups()
        return _format_date(year, month, day)

    if match := YYYY_MM_DD_PATTERN.search(filename):
        year, month, day = match.groups()
        return _format_date(year, month, day)

    if match := DDMMYY_COMPACT_PATTERN.match(filename):
        day, month, year = match.groups()
        return _format_date(year, month, day)

    if match := DATE_PATTERN.search(filename):
        day, month, year = match.groups()
        return _format_date(year, month, day)

    if match := DATE_SPACE_PATTERN.search(filename):
        day, month, year = match.groups()
        return _format_date(year, month, day)

    if match := YYYY_MM_PATTERN.search(filename):
        year, month = match.groups()
        return f"{year}-{int(month):02d}-01"

    return DEFAULT_DATE
