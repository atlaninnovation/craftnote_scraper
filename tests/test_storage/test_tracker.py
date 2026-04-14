from datetime import datetime
from pathlib import Path

import pytest

from craftnote_scraper.storage.models import DownloadedFile, FileType
from craftnote_scraper.storage.tracker import DownloadTracker


@pytest.fixture
def tracker(tmp_path: Path) -> DownloadTracker:
    return DownloadTracker(db_path=tmp_path / "test.db")


@pytest.fixture
def sample_file() -> DownloadedFile:
    return DownloadedFile(
        file_id="file-123",
        filename="report.pdf",
        file_type=FileType.PDF,
        downloaded_at=datetime(2024, 1, 15, 10, 30, 0),
        path=Path("downloads/Boddin/BO1/report.pdf"),
        checksum="abc123def456",
        wind_farm="Boddin",
        turbine="BO1",
    )


class TestDownloadTracker:
    def test_is_already_downloaded_returns_false_for_new_file(self, tracker: DownloadTracker):
        assert tracker.is_already_downloaded("nonexistent") is False

    def test_is_already_downloaded_returns_true_after_recording(
        self, tracker: DownloadTracker, sample_file: DownloadedFile
    ):
        tracker.record_download(sample_file)

        assert tracker.is_already_downloaded(sample_file.file_id) is True

    def test_is_duplicate_checksum_detects_duplicates(
        self, tracker: DownloadTracker, sample_file: DownloadedFile
    ):
        tracker.record_download(sample_file)

        assert tracker.is_duplicate_checksum(sample_file.checksum) is True
        assert tracker.is_duplicate_checksum("different-checksum") is False

    def test_get_download_returns_none_for_unknown(self, tracker: DownloadTracker):
        assert tracker.get_download("nonexistent") is None

    def test_get_download_returns_recorded_file(
        self, tracker: DownloadTracker, sample_file: DownloadedFile
    ):
        tracker.record_download(sample_file)

        result = tracker.get_download(sample_file.file_id)

        assert result is not None
        assert result.file_id == sample_file.file_id
        assert result.filename == sample_file.filename
        assert result.file_type == sample_file.file_type
        assert result.downloaded_at == sample_file.downloaded_at
        assert result.path == sample_file.path
        assert result.checksum == sample_file.checksum
        assert result.wind_farm == sample_file.wind_farm
        assert result.turbine == sample_file.turbine

    def test_record_download_updates_existing(
        self, tracker: DownloadTracker, sample_file: DownloadedFile
    ):
        tracker.record_download(sample_file)

        updated_file = DownloadedFile(
            file_id=sample_file.file_id,
            filename="updated.pdf",
            file_type=FileType.PDF,
            downloaded_at=datetime(2024, 2, 1, 12, 0, 0),
            path=Path("downloads/Boddin/BO1/updated.pdf"),
            checksum="newchecksum",
            wind_farm="Boddin",
            turbine="BO1",
        )
        tracker.record_download(updated_file)

        result = tracker.get_download(sample_file.file_id)
        assert result is not None
        assert result.filename == "updated.pdf"

    def test_get_download_history_returns_empty_for_no_records(self, tracker: DownloadTracker):
        assert tracker.get_download_history() == []

    def test_get_download_history_returns_all_records(self, tracker: DownloadTracker):
        file1 = DownloadedFile(
            file_id="file-1",
            filename="report1.pdf",
            file_type=FileType.PDF,
            downloaded_at=datetime(2024, 1, 15, 10, 0, 0),
            path=Path("downloads/Boddin/BO1/report1.pdf"),
            checksum="checksum1",
            wind_farm="Boddin",
            turbine="BO1",
        )
        file2 = DownloadedFile(
            file_id="file-2",
            filename="report2.xlsx",
            file_type=FileType.XLSX,
            downloaded_at=datetime(2024, 1, 16, 11, 0, 0),
            path=Path("downloads/Giersleben/GIER01/report2.xlsx"),
            checksum="checksum2",
            wind_farm="Giersleben",
            turbine="GIER01",
        )
        tracker.record_download(file1)
        tracker.record_download(file2)

        history = tracker.get_download_history()

        assert len(history) == 2

    def test_get_download_history_filters_by_wind_farm(self, tracker: DownloadTracker):
        file1 = DownloadedFile(
            file_id="file-1",
            filename="report1.pdf",
            file_type=FileType.PDF,
            downloaded_at=datetime(2024, 1, 15, 10, 0, 0),
            path=Path("downloads/Boddin/BO1/report1.pdf"),
            checksum="checksum1",
            wind_farm="Boddin",
            turbine="BO1",
        )
        file2 = DownloadedFile(
            file_id="file-2",
            filename="report2.xlsx",
            file_type=FileType.XLSX,
            downloaded_at=datetime(2024, 1, 16, 11, 0, 0),
            path=Path("downloads/Giersleben/GIER01/report2.xlsx"),
            checksum="checksum2",
            wind_farm="Giersleben",
            turbine="GIER01",
        )
        tracker.record_download(file1)
        tracker.record_download(file2)

        boddin_history = tracker.get_download_history(wind_farm="Boddin")

        assert len(boddin_history) == 1
        assert boddin_history[0].wind_farm == "Boddin"

    def test_persists_across_instances(self, tmp_path: Path):
        db_path = tmp_path / "persistent.db"
        file = DownloadedFile(
            file_id="persistent-file",
            filename="test.pdf",
            file_type=FileType.PDF,
            downloaded_at=datetime(2024, 1, 15, 10, 0, 0),
            path=Path("downloads/Farm/Turbine/test.pdf"),
            checksum="persistent-checksum",
            wind_farm="Farm",
            turbine="Turbine",
        )

        tracker1 = DownloadTracker(db_path=db_path)
        tracker1.record_download(file)

        tracker2 = DownloadTracker(db_path=db_path)
        assert tracker2.is_already_downloaded(file.file_id) is True
