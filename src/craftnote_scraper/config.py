from typing import Final

DEFAULT_OUTPUT_DIR: Final[str] = "downloads"
DEFAULT_DB_PATH: Final[str] = "downloads.db"
DEFAULT_MATRIX_MAPPING_PATH: Final[str] = "learning/wind-farm-spaces.md"

DEFAULT_SYNC_LOOKBACK_HOURS: Final[int] = 24
DEFAULT_SYNC_SCHEDULE: Final[str] = "0 20 * * *"

EXCLUDED_FOLDERS: Final[frozenset[str]] = frozenset(
    {
        "Beispiel-Projekt",
        "DFÜ",
        "Doku Unterkunft",
        "Eimsbüttler Chaussee",
        "Einbruchschaden Langendorf",
        "Fremdaufträge",
        "Fuhrpark",
        "Gewährleistung",
        "Immobilien",
        "Immobilien Hamburg",
        "IT Projekte ",
        "IT-Projekte",
        "Koordinaten Windparks",
        "Lager",
        "Marketing",
        "Meldung Fernüberwachung",
        "Projekte",
        "Rechnungen Scan",
        "Sommerfest 2021",
        "Starlink Görlitz",
        "Test",
        "Unternehmens-Chat",
        "Versicherungsfälle",
        "Versicherungsschäden",
        "Windkraftmesse 2024",
    }
)
