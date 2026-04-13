from dataclasses import dataclass, field


@dataclass(frozen=True)
class WindTurbine:
    craftnote_project_id: str
    name: str
    matrix_room_id: str | None = None


@dataclass(frozen=True)
class WindFarm:
    name: str
    craftnote_folder_id: str | None = None
    matrix_space_id: str | None = None
    matrix_access_room_id: str | None = None
    turbines: tuple[WindTurbine, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class MatrixRoom:
    room_id: str
    name: str


@dataclass(frozen=True)
class MatrixWindFarm:
    name: str
    space_id: str
    access_room_id: str | None = None
    turbine_rooms: tuple[MatrixRoom, ...] = field(default_factory=tuple)
