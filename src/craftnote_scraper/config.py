from typing import Final

DEFAULT_OUTPUT_DIR: Final[str] = "downloads"
DEFAULT_DB_PATH: Final[str] = "downloads.db"
DEFAULT_MATRIX_MAPPING_PATH: Final[str] = "learning/wind-farm-spaces.md"

DEFAULT_SYNC_LOOKBACK_HOURS: Final[int] = 24
DEFAULT_SYNC_SCHEDULE: Final[str] = "0 20 * * *"

EXCLUDED_FOLDERS: Final[frozenset[str]] = frozenset(
    {
        "DFÜ",
        "IT Projekte ",
        "IT-Projekte",
        "Koordinaten Windparks",
        "Lager",
        "Marketing",
        "Projekte",
        "Rechnungen Scan",
        "Starlink Görlitz",
        "Test",
        "Unternehmens-Chat",
        "Doku Unterkunft",
        "Eimsbüttler Chaussee",
        "Immobilien",
        "Immobilien Hamburg",
        "Einbruchschaden Langendorf",
        "Gewährleistung",
        "Versicherungsfälle",
        "Versicherungsschäden",
        "Beispiel-Projekt",
        "Fremdaufträge",
        "Fuhrpark",
        "Sommerfest 2021",
        "Windkraftmesse 2024",
    }
)
