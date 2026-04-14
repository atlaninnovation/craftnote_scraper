from craftnote_scraper.storage.minio_adapter import (
    ContentType,
    extract_date_from_filename,
)


class TestContentType:
    def test_from_extension_pdf(self):
        assert ContentType.from_extension(".pdf") == ContentType.PDF
        assert ContentType.from_extension(".PDF") == ContentType.PDF

    def test_from_extension_xlsx(self):
        assert ContentType.from_extension(".xlsx") == ContentType.XLSX
        assert ContentType.from_extension(".XLSX") == ContentType.XLSX

    def test_from_extension_xls(self):
        assert ContentType.from_extension(".xls") == ContentType.XLS

    def test_from_extension_unknown(self):
        assert ContentType.from_extension(".txt") == ContentType.OCTET_STREAM
        assert ContentType.from_extension(".doc") == ContentType.OCTET_STREAM
        assert ContentType.from_extension("") == ContentType.OCTET_STREAM


class TestExtractDateFromFilename:
    def test_german_date_format(self):
        assert extract_date_from_filename("Servicebericht Boddin 6.5.2025.pdf") == "2025-05-06"
        assert extract_date_from_filename("Report 12.03.2024.xlsx") == "2024-03-12"

    def test_iso_date_format(self):
        assert extract_date_from_filename("Report 2025-05-06.pdf") == "2025-05-06"
        assert extract_date_from_filename("2024-12-31_servicebericht.pdf") == "2024-12-31"

    def test_dash_separated_date(self):
        assert extract_date_from_filename("WEA4_12-05-2025.xlsx") == "2025-05-12"
        assert extract_date_from_filename("Report-01-12-2024.pdf") == "2024-12-01"

    def test_slash_separated_date(self):
        assert extract_date_from_filename("Report 6/5/2025.pdf") == "2025-05-06"

    def test_two_digit_year(self):
        assert extract_date_from_filename("Bericht 15.06.25.pdf") == "2025-06-15"
        assert extract_date_from_filename("Report 1.2.24.xlsx") == "2024-02-01"

    def test_no_date_returns_default(self):
        assert extract_date_from_filename("servicebericht.pdf") == "unknown-date"
        assert extract_date_from_filename("WEA4_report.xlsx") == "unknown-date"
        assert extract_date_from_filename("Angebot_G12500229.pdf") == "unknown-date"

    def test_single_digit_day_month(self):
        assert extract_date_from_filename("Report 1.2.2025.pdf") == "2025-02-01"
        assert extract_date_from_filename("2025-1-2_file.pdf") == "2025-01-02"

    def test_ddmmyy_compact_at_start(self):
        assert extract_date_from_filename("230725 BA2.pdf") == "2025-07-23"
        assert extract_date_from_filename("010824 TA2.pdf") == "2024-08-01"
        assert extract_date_from_filename("120225 SSD R43036.pdf") == "2025-02-12"
        assert extract_date_from_filename("020625 R43046.pdf") == "2025-06-02"

    def test_yyyymmdd_with_underscores(self):
        assert extract_date_from_filename("70282_FLE02_20260215_203337999.xls") == "2026-02-15"
        assert extract_date_from_filename("GE_15560445_05_20260324.pdf") == "2026-03-24"
        assert extract_date_from_filename("JW_48066_20260119_184300352.xlsx") == "2026-01-19"

    def test_yyyymmdd_with_spaces(self):
        assert extract_date_from_filename("Report 20260315 final.pdf") == "2026-03-15"

    def test_yyyy_mm_only(self):
        assert extract_date_from_filename("2024-06_Sicherheitsprufung.pdf") == "2024-06-01"
        assert extract_date_from_filename("2025-12_Kettenzuge_FORMULAR.pdf") == "2025-12-01"

    def test_dd_space_mm_yyyy(self):
        assert extract_date_from_filename("Servicebericht 02 04.2026 TWH.pdf") == "2026-04-02"
        assert extract_date_from_filename("Report 13 03.2026 file.xlsx") == "2026-03-13"

    def test_prefers_yyyymmdd_over_other_formats(self):
        filename = "Report_20260506_with_date_1.2.2024.pdf"
        assert extract_date_from_filename(filename) == "2026-05-06"
