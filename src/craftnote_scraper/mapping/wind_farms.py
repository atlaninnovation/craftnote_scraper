import logging
import re
import time
from pathlib import Path
from typing import Final

from craftnote_scraper.api.client import CraftnoteClient
from craftnote_scraper.api.models import Project, ProjectType
from craftnote_scraper.mapping.models import (
    MatrixRoom,
    MatrixWindFarm,
    WindFarm,
    WindTurbine,
)

logger = logging.getLogger(__name__)

ACCESS_ROOM_MARKER: Final[str] = "Anlagenzugang"
SPACE_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"\*\*Space ID:\*\*\s*`([^`]+)`")
ROOM_PATTERN: Final[re.Pattern[str]] = re.compile(r"-\s*\*\*([^*]+)\*\*:\s*`([^`]+)`")
WIND_FARM_HEADER_PATTERN: Final[re.Pattern[str]] = re.compile(r"^##\s+(.+)$")
TURBINE_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^(?:([A-Za-z]+\d*)\s*)?(\d+)\s*-\s*(.+)$"
)
SERIAL_NUMBER_PATTERN: Final[re.Pattern[str]] = re.compile(r"\b(\d{5,})\b")
SECONDS_PER_DAY: Final[int] = 86400
DEFAULT_MAX_INACTIVE_DAYS: Final[int] = 365


def parse_matrix_wind_farms(markdown_path: Path) -> list[MatrixWindFarm]:
    content = markdown_path.read_text(encoding="utf-8")
    lines = content.splitlines()

    wind_farms: list[MatrixWindFarm] = []
    current_name: str | None = None
    current_space_id: str | None = None
    current_rooms: list[MatrixRoom] = []
    current_access_room: str | None = None

    for line in lines:
        header_match = WIND_FARM_HEADER_PATTERN.match(line)
        if header_match:
            if current_name and current_space_id:
                wind_farms.append(
                    MatrixWindFarm(
                        name=current_name,
                        space_id=current_space_id,
                        access_room_id=current_access_room,
                        turbine_rooms=tuple(current_rooms),
                    )
                )
            current_name = header_match.group(1).strip()
            current_space_id = None
            current_rooms = []
            current_access_room = None
            continue

        space_match = SPACE_ID_PATTERN.search(line)
        if space_match:
            current_space_id = space_match.group(1)
            continue

        room_match = ROOM_PATTERN.match(line.strip())
        if room_match:
            room_name = room_match.group(1).strip()
            room_id = room_match.group(2).strip()

            if ACCESS_ROOM_MARKER in room_name:
                current_access_room = room_id
            else:
                current_rooms.append(MatrixRoom(room_id=room_id, name=room_name))

    if current_name and current_space_id:
        wind_farms.append(
            MatrixWindFarm(
                name=current_name,
                space_id=current_space_id,
                access_room_id=current_access_room,
                turbine_rooms=tuple(current_rooms),
            )
        )

    return wind_farms


def normalize_name(name: str) -> str:
    import unicodedata

    normalized = unicodedata.normalize("NFKD", name)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", ascii_text.lower())


def fuzzy_match_wind_farm(
    craftnote_name: str,
    matrix_farms: list[MatrixWindFarm],
) -> MatrixWindFarm | None:
    normalized_craftnote = normalize_name(craftnote_name)

    for matrix_farm in matrix_farms:
        if normalize_name(matrix_farm.name) == normalized_craftnote:
            return matrix_farm

    for matrix_farm in matrix_farms:
        matrix_normalized = normalize_name(matrix_farm.name)
        if matrix_normalized in normalized_craftnote or normalized_craftnote in matrix_normalized:
            return matrix_farm

    return None


def parse_turbine_name(name: str) -> tuple[str | None, str | None, str | None]:
    match = TURBINE_NAME_PATTERN.match(name.strip())
    if not match:
        return None, None, None
    prefix = match.group(1)
    number = match.group(2)
    serial = match.group(3).strip()
    return prefix, number, serial


def extract_serial_numbers(name: str) -> list[str]:
    return SERIAL_NUMBER_PATTERN.findall(name)


def match_turbine_to_room(
    turbine_name: str,
    matrix_rooms: tuple[MatrixRoom, ...],
) -> str | None:
    turbine_normalized = normalize_name(turbine_name)

    for room in matrix_rooms:
        if normalize_name(room.name) == turbine_normalized:
            return room.room_id

    turbine_serials = extract_serial_numbers(turbine_name)
    if turbine_serials:
        for room in matrix_rooms:
            room_serials = extract_serial_numbers(room.name)
            for serial in turbine_serials:
                if serial in room_serials:
                    return room.room_id

    prefix, number, serial = parse_turbine_name(turbine_name)
    if serial:
        for room in matrix_rooms:
            if serial in room.name:
                return room.room_id

    if number:
        for room in matrix_rooms:
            room_prefix, room_number, _ = parse_turbine_name(room.name)
            if room_number == number:
                if prefix and room_prefix:
                    if normalize_name(prefix) == normalize_name(room_prefix):
                        return room.room_id
                elif not prefix and not room_prefix:
                    return room.room_id

    return None


def _is_project_active(project: Project, max_inactive_days: int | None) -> bool:
    """Check if a project was edited within the allowed inactive period."""
    if max_inactive_days is None:
        return True

    last_edit = project.last_edited_date or project.last_opened_date
    if last_edit is None:
        return False

    cutoff_timestamp = int(time.time()) - (max_inactive_days * SECONDS_PER_DAY)
    return last_edit >= cutoff_timestamp


async def discover_craftnote_structure(
    client: CraftnoteClient,
    max_inactive_days: int | None = DEFAULT_MAX_INACTIVE_DAYS,
) -> dict[str, list[Project]]:
    """
    Discover Craftnote folder structure with projects.

    Args:
        client: Craftnote API client.
        max_inactive_days: Exclude projects not edited within this many days.
            Set to None to include all projects.

    Returns:
        Dict mapping folder names to lists of child projects.
    """
    folders: dict[str, Project] = {}
    projects_by_parent: dict[str, list[Project]] = {}

    async for project in client.iter_all_projects():
        if project.project_type == ProjectType.FOLDER:
            folders[project.id] = project
        elif project.parent_project:
            if not _is_project_active(project, max_inactive_days):
                continue
            if project.parent_project not in projects_by_parent:
                projects_by_parent[project.parent_project] = []
            projects_by_parent[project.parent_project].append(project)

    wind_farm_structure: dict[str, list[Project]] = {}
    for folder_id, folder in folders.items():
        if folder_id in projects_by_parent:
            wind_farm_structure[folder.name] = projects_by_parent[folder_id]

    return wind_farm_structure


async def build_wind_farm_map(
    client: CraftnoteClient,
    matrix_farms: list[MatrixWindFarm],
    max_inactive_days: int | None = DEFAULT_MAX_INACTIVE_DAYS,
) -> list[WindFarm]:
    """
    Build wind farm mapping between Craftnote and Matrix.

    Args:
        client: Craftnote API client.
        matrix_farms: List of Matrix wind farms to match against.
        max_inactive_days: Exclude projects not edited within this many days.
            Set to None to include all projects. Defaults to 365 days.

    Returns:
        List of WindFarm objects with matched turbines.
    """
    craftnote_structure = await discover_craftnote_structure(client, max_inactive_days)
    wind_farms: list[WindFarm] = []

    folders: dict[str, Project] = {}
    async for project in client.iter_all_projects():
        if project.project_type == ProjectType.FOLDER:
            folders[project.name] = project

    for farm_name, turbine_projects in craftnote_structure.items():
        matrix_farm = fuzzy_match_wind_farm(farm_name, matrix_farms)

        if matrix_farm:
            logger.info("Matched Craftnote '%s' to Matrix '%s'", farm_name, matrix_farm.name)
        else:
            logger.warning("No Matrix match found for Craftnote wind farm: %s", farm_name)

        turbines: list[WindTurbine] = []
        for project in turbine_projects:
            matrix_room_id = None
            if matrix_farm:
                matrix_room_id = match_turbine_to_room(project.name, matrix_farm.turbine_rooms)
                if matrix_room_id:
                    logger.debug("Matched turbine '%s' to room", project.name)
                else:
                    logger.warning("No Matrix room found for turbine: %s", project.name)

            turbines.append(
                WindTurbine(
                    craftnote_project_id=project.id,
                    name=project.name,
                    matrix_room_id=matrix_room_id,
                )
            )

        folder = folders.get(farm_name)
        wind_farms.append(
            WindFarm(
                name=farm_name,
                craftnote_folder_id=folder.id if folder else None,
                matrix_space_id=matrix_farm.space_id if matrix_farm else None,
                matrix_access_room_id=matrix_farm.access_room_id if matrix_farm else None,
                turbines=tuple(turbines),
            )
        )

    matched_matrix_names: set[str] = set()
    for name in craftnote_structure:
        matched_farm = fuzzy_match_wind_farm(name, matrix_farms)
        if matched_farm:
            matched_matrix_names.add(normalize_name(matched_farm.name))

    for matrix_farm in matrix_farms:
        if normalize_name(matrix_farm.name) not in matched_matrix_names:
            logger.warning("Matrix wind farm has no Craftnote match: %s", matrix_farm.name)
            wind_farms.append(
                WindFarm(
                    name=matrix_farm.name,
                    craftnote_folder_id=None,
                    matrix_space_id=matrix_farm.space_id,
                    matrix_access_room_id=matrix_farm.access_room_id,
                    turbines=tuple(
                        WindTurbine(
                            craftnote_project_id="",
                            name=room.name,
                            matrix_room_id=room.room_id,
                        )
                        for room in matrix_farm.turbine_rooms
                    ),
                )
            )

    return wind_farms


def get_all_turbine_projects(wind_farms: list[WindFarm]) -> list[str]:
    return [
        turbine.craftnote_project_id
        for farm in wind_farms
        for turbine in farm.turbines
        if turbine.craftnote_project_id
    ]


def get_unmatched_turbines(wind_farms: list[WindFarm]) -> list[WindTurbine]:
    return [
        turbine
        for farm in wind_farms
        for turbine in farm.turbines
        if turbine.craftnote_project_id and not turbine.matrix_room_id
    ]


def get_unmatched_matrix_rooms(wind_farms: list[WindFarm]) -> list[tuple[str, MatrixRoom]]:
    unmatched: list[tuple[str, MatrixRoom]] = []
    for farm in wind_farms:
        if not farm.craftnote_folder_id and farm.matrix_space_id:
            for turbine in farm.turbines:
                if turbine.matrix_room_id:
                    unmatched.append(
                        (farm.name, MatrixRoom(room_id=turbine.matrix_room_id, name=turbine.name))
                    )
    return unmatched
