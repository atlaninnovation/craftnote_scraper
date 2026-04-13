from pathlib import Path
from textwrap import dedent

import pytest

from craftnote_scraper.mapping.models import MatrixRoom, MatrixWindFarm, WindFarm, WindTurbine
from craftnote_scraper.mapping.wind_farms import (
    extract_serial_numbers,
    fuzzy_match_wind_farm,
    get_all_turbine_projects,
    get_unmatched_turbines,
    match_turbine_to_room,
    normalize_name,
    parse_matrix_wind_farms,
    parse_turbine_name,
)


class TestNormalizeName:
    def test_removes_special_characters(self):
        assert normalize_name("Buchholz-Birkstücke") == "buchholzbirkstucke"

    def test_lowercases(self):
        assert normalize_name("BADEL") == "badel"

    def test_removes_spaces(self):
        assert normalize_name("Hanstedt 2") == "hanstedt2"


class TestParseTurbineName:
    def test_with_prefix_and_serial(self):
        prefix, number, serial = parse_turbine_name("BO1 - 16562")
        assert prefix == "BO"
        assert number == "1"
        assert serial == "16562"

    def test_with_prefix_space_number(self):
        prefix, number, serial = parse_turbine_name("GIER 01 - 51089")
        assert prefix == "GIER"
        assert number == "01"
        assert serial == "51089"

    def test_number_only(self):
        prefix, number, serial = parse_turbine_name("01 - 21421")
        assert prefix is None
        assert number == "01"
        assert serial == "21421"

    def test_alphanumeric_prefix(self):
        prefix, number, serial = parse_turbine_name("S77 01 - 70282")
        assert prefix == "S77"
        assert number == "01"
        assert serial == "70282"

    def test_vestas_serial(self):
        prefix, number, serial = parse_turbine_name("01 - V22954")
        assert prefix is None
        assert number == "01"
        assert serial == "V22954"

    def test_with_suffix(self):
        prefix, number, serial = parse_turbine_name("03 - 15533146 - Master")
        assert prefix is None
        assert number == "03"
        assert serial == "15533146 - Master"

    def test_invalid_format(self):
        prefix, number, serial = parse_turbine_name("invalid name")
        assert prefix is None
        assert number is None
        assert serial is None


class TestExtractSerialNumbers:
    def test_extracts_5_digit_serial(self):
        assert extract_serial_numbers("BO1 - 16562") == ["16562"]

    def test_extracts_8_digit_serial(self):
        assert extract_serial_numbers("GE 15560459 (17)") == ["15560459"]

    def test_extracts_multiple_serials(self):
        serials = extract_serial_numbers("Serial 12345 and 67890")
        assert "12345" in serials
        assert "67890" in serials

    def test_ignores_short_numbers(self):
        assert extract_serial_numbers("BO1 - 123") == []

    def test_extracts_from_craftnote_format(self):
        assert extract_serial_numbers("HJW 43046") == ["43046"]

    def test_extracts_from_parentheses(self):
        assert extract_serial_numbers("GIER 17 (51080)") == ["51080"]


class TestParseMatrixWindFarms:
    def test_parses_wind_farm_with_turbines(self, tmp_path: Path):
        markdown = dedent("""
            ## Boddin

            **Space ID:** `!JolmkGPegNnHOWyePy:matrix.windreserve.de`

            ### Rooms

            - **Anlagenzugang | Wind Farm Access**: `!RtaivLvudkSoPPMulW:matrix.windreserve.de`
            - **BO1 - 16562**: `!SQqWBcnerkrXAWzPKL:matrix.windreserve.de`
            - **BO2 - 16534**: `!ToklfkyRfcDQISQgGh:matrix.windreserve.de`
        """)
        md_file = tmp_path / "test.md"
        md_file.write_text(markdown)

        farms = parse_matrix_wind_farms(md_file)

        assert len(farms) == 1
        farm = farms[0]
        assert farm.name == "Boddin"
        assert farm.space_id == "!JolmkGPegNnHOWyePy:matrix.windreserve.de"
        assert farm.access_room_id == "!RtaivLvudkSoPPMulW:matrix.windreserve.de"
        assert len(farm.turbine_rooms) == 2
        assert farm.turbine_rooms[0].name == "BO1 - 16562"
        assert farm.turbine_rooms[0].room_id == "!SQqWBcnerkrXAWzPKL:matrix.windreserve.de"

    def test_parses_multiple_wind_farms(self, tmp_path: Path):
        markdown = dedent("""
            ## Badel 2b

            **Space ID:** `!UKcBOSDqDrpTDSgqNU:matrix.windreserve.de`

            ### Rooms

            - **Anlagenzugang | Wind Farm Access**: `!NqlWVLFuWKMyQSyKAo:matrix.windreserve.de`

            ---

            ## Boddin

            **Space ID:** `!JolmkGPegNnHOWyePy:matrix.windreserve.de`

            ### Rooms

            - **Anlagenzugang | Wind Farm Access**: `!RtaivLvudkSoPPMulW:matrix.windreserve.de`
        """)
        md_file = tmp_path / "test.md"
        md_file.write_text(markdown)

        farms = parse_matrix_wind_farms(md_file)

        assert len(farms) == 2
        assert farms[0].name == "Badel 2b"
        assert farms[1].name == "Boddin"


class TestFuzzyMatchWindFarm:
    @pytest.fixture
    def matrix_farms(self) -> list[MatrixWindFarm]:
        return [
            MatrixWindFarm(name="Badel 2b", space_id="!space1"),
            MatrixWindFarm(name="Buchholz-Birkstücke", space_id="!space2"),
            MatrixWindFarm(name="Hanstedt 2", space_id="!space3"),
            MatrixWindFarm(name="Frehne Nord", space_id="!space4"),
            MatrixWindFarm(name="Frehne West", space_id="!space5"),
        ]

    def test_exact_match(self, matrix_farms: list[MatrixWindFarm]):
        result = fuzzy_match_wind_farm("Badel 2b", matrix_farms)
        assert result is not None
        assert result.name == "Badel 2b"

    def test_normalized_match(self, matrix_farms: list[MatrixWindFarm]):
        result = fuzzy_match_wind_farm("buchholzbirkstucke", matrix_farms)
        assert result is not None
        assert result.name == "Buchholz-Birkstücke"

    def test_substring_match(self, matrix_farms: list[MatrixWindFarm]):
        result = fuzzy_match_wind_farm("Hanstedt 2 Erweiterung", matrix_farms)
        assert result is not None
        assert result.name == "Hanstedt 2"

    def test_no_match(self, matrix_farms: list[MatrixWindFarm]):
        result = fuzzy_match_wind_farm("Unknown Farm", matrix_farms)
        assert result is None


class TestMatchTurbineToRoom:
    @pytest.fixture
    def matrix_rooms(self) -> tuple[MatrixRoom, ...]:
        return (
            MatrixRoom(room_id="!room1", name="BO1 - 16562"),
            MatrixRoom(room_id="!room2", name="BO2 - 16534"),
            MatrixRoom(room_id="!room3", name="01 - 21421"),
            MatrixRoom(room_id="!room4", name="07 - 15560447"),
        )

    def test_exact_match(self, matrix_rooms: tuple[MatrixRoom, ...]):
        result = match_turbine_to_room("BO1 - 16562", matrix_rooms)
        assert result == "!room1"

    def test_serial_match(self, matrix_rooms: tuple[MatrixRoom, ...]):
        result = match_turbine_to_room("BO2 - 16534", matrix_rooms)
        assert result == "!room2"

    def test_serial_extraction_match(self, matrix_rooms: tuple[MatrixRoom, ...]):
        result = match_turbine_to_room("GE 15560447 (07)", matrix_rooms)
        assert result == "!room4"

    def test_craftnote_task_format_match(self, matrix_rooms: tuple[MatrixRoom, ...]):
        result = match_turbine_to_room("HJW 16562", matrix_rooms)
        assert result == "!room1"

    def test_no_match(self, matrix_rooms: tuple[MatrixRoom, ...]):
        result = match_turbine_to_room("Unknown Turbine", matrix_rooms)
        assert result is None


class TestGetAllTurbineProjects:
    def test_returns_all_project_ids(self):
        wind_farms = [
            WindFarm(
                name="Farm1",
                turbines=(
                    WindTurbine(craftnote_project_id="p1", name="T1"),
                    WindTurbine(craftnote_project_id="p2", name="T2"),
                ),
            ),
            WindFarm(
                name="Farm2",
                turbines=(WindTurbine(craftnote_project_id="p3", name="T3"),),
            ),
        ]

        result = get_all_turbine_projects(wind_farms)

        assert result == ["p1", "p2", "p3"]

    def test_excludes_empty_project_ids(self):
        wind_farms = [
            WindFarm(
                name="Farm1",
                turbines=(
                    WindTurbine(craftnote_project_id="p1", name="T1"),
                    WindTurbine(craftnote_project_id="", name="T2", matrix_room_id="!room"),
                ),
            ),
        ]

        result = get_all_turbine_projects(wind_farms)

        assert result == ["p1"]


class TestGetUnmatchedTurbines:
    def test_returns_turbines_without_matrix_room(self):
        wind_farms = [
            WindFarm(
                name="Farm1",
                turbines=(
                    WindTurbine(craftnote_project_id="p1", name="T1", matrix_room_id="!room"),
                    WindTurbine(craftnote_project_id="p2", name="T2"),
                ),
            ),
        ]

        result = get_unmatched_turbines(wind_farms)

        assert len(result) == 1
        assert result[0].craftnote_project_id == "p2"

    def test_excludes_matrix_only_turbines(self):
        wind_farms = [
            WindFarm(
                name="Farm1",
                turbines=(WindTurbine(craftnote_project_id="", name="T1", matrix_room_id="!room"),),
            ),
        ]

        result = get_unmatched_turbines(wind_farms)

        assert result == []
