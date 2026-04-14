from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path


class FileType(Enum):
    PDF = "pdf"
    XLSX = "xlsx"
    XLS = "xls"
    UNKNOWN = "unknown"

    @classmethod
    def from_filename(cls, filename: str) -> "FileType":
        suffix = Path(filename).suffix.lower().lstrip(".")
        try:
            return cls(suffix)
        except ValueError:
            return cls.UNKNOWN


@dataclass(frozen=True)
class DownloadedFile:
    file_id: str
    filename: str
    file_type: FileType
    downloaded_at: datetime
    path: Path
    checksum: str
    wind_farm: str
    turbine: str
    minio_object_key: str | None = None
    minio_uploaded_at: datetime | None = None
