import hashlib
import re
from pathlib import Path
from typing import Final

HASH_ALGORITHM: Final[str] = "sha256"
HASH_CHUNK_SIZE: Final[int] = 8192
DEFAULT_DOWNLOADS_DIR: Final[str] = "downloads"


def sanitize_filename(name: str) -> str:
    """Remove or replace characters that are invalid in file paths."""
    sanitized = re.sub(r'[<>:"/\\|?*]', "_", name)
    sanitized = sanitized.strip(". ")
    return sanitized or "unnamed"


def get_download_path(
    wind_farm: str,
    turbine: str,
    filename: str,
    base_dir: Path | None = None,
) -> Path:
    """Compute the target path for a downloaded file."""
    base = base_dir or Path(DEFAULT_DOWNLOADS_DIR)
    safe_wind_farm = sanitize_filename(wind_farm)
    safe_turbine = sanitize_filename(turbine)
    safe_filename = sanitize_filename(filename)
    return base / safe_wind_farm / safe_turbine / safe_filename


def resolve_collision(path: Path) -> Path:
    """Return a non-colliding path by appending a counter if needed."""
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 1

    while True:
        new_path = parent / f"{stem}_{counter}{suffix}"
        if not new_path.exists():
            return new_path
        counter += 1


def compute_checksum(file_path: Path) -> str:
    """Compute SHA256 checksum of a file."""
    hasher = hashlib.new(HASH_ALGORITHM)
    with file_path.open("rb") as f:
        while chunk := f.read(HASH_CHUNK_SIZE):
            hasher.update(chunk)
    return hasher.hexdigest()


def compute_checksum_from_bytes(content: bytes) -> str:
    """Compute SHA256 checksum from bytes."""
    return hashlib.new(HASH_ALGORITHM, content).hexdigest()


def save_file(
    content: bytes,
    wind_farm: str,
    turbine: str,
    filename: str,
    base_dir: Path | None = None,
    handle_collision: bool = True,
) -> tuple[Path, str]:
    """
    Save file content to the appropriate location.

    Returns the final path and checksum.
    """
    target_path = get_download_path(wind_farm, turbine, filename, base_dir)

    if handle_collision:
        target_path = resolve_collision(target_path)

    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(content)
    checksum = compute_checksum_from_bytes(content)

    return target_path, checksum
