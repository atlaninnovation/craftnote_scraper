from pathlib import Path

from craftnote_scraper.storage.organizer import (
    compute_checksum,
    compute_checksum_from_bytes,
    get_download_path,
    resolve_collision,
    sanitize_filename,
    save_file,
)


class TestSanitizeFilename:
    def test_removes_invalid_characters(self):
        assert sanitize_filename('file<>:"/\\|?*.txt') == "file_________.txt"

    def test_strips_dots_and_spaces(self):
        assert sanitize_filename("  file.txt  ") == "file.txt"
        assert sanitize_filename("...file.txt...") == "file.txt"

    def test_returns_unnamed_for_empty(self):
        assert sanitize_filename("") == "unnamed"
        assert sanitize_filename("...") == "unnamed"

    def test_preserves_valid_filename(self):
        assert sanitize_filename("valid_file-name.pdf") == "valid_file-name.pdf"


class TestGetDownloadPath:
    def test_creates_correct_path(self):
        path = get_download_path("Boddin", "BO1-16562", "report.pdf")
        assert path == Path("downloads/Boddin/BO1-16562/report.pdf")

    def test_uses_custom_base_dir(self, tmp_path: Path):
        path = get_download_path("Farm", "Turbine", "file.xlsx", base_dir=tmp_path)
        assert path == tmp_path / "Farm" / "Turbine" / "file.xlsx"

    def test_sanitizes_all_components(self):
        path = get_download_path("Farm/Name", "Turbine:1", "file?.pdf")
        assert path == Path("downloads/Farm_Name/Turbine_1/file_.pdf")


class TestResolveCollision:
    def test_returns_original_if_no_collision(self, tmp_path: Path):
        path = tmp_path / "file.pdf"
        assert resolve_collision(path) == path

    def test_appends_counter_on_collision(self, tmp_path: Path):
        original = tmp_path / "file.pdf"
        original.touch()

        result = resolve_collision(original)

        assert result == tmp_path / "file_1.pdf"

    def test_increments_counter_for_multiple_collisions(self, tmp_path: Path):
        original = tmp_path / "file.pdf"
        original.touch()
        (tmp_path / "file_1.pdf").touch()
        (tmp_path / "file_2.pdf").touch()

        result = resolve_collision(original)

        assert result == tmp_path / "file_3.pdf"


class TestComputeChecksum:
    def test_computes_sha256(self, tmp_path: Path):
        test_file = tmp_path / "test.txt"
        test_file.write_bytes(b"hello world")

        checksum = compute_checksum(test_file)

        expected = "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
        assert checksum == expected

    def test_consistent_for_same_content(self, tmp_path: Path):
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_bytes(b"same content")
        file2.write_bytes(b"same content")

        assert compute_checksum(file1) == compute_checksum(file2)

    def test_different_for_different_content(self, tmp_path: Path):
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_bytes(b"content a")
        file2.write_bytes(b"content b")

        assert compute_checksum(file1) != compute_checksum(file2)


class TestComputeChecksumFromBytes:
    def test_matches_file_checksum(self, tmp_path: Path):
        content = b"test content"
        test_file = tmp_path / "test.txt"
        test_file.write_bytes(content)

        assert compute_checksum_from_bytes(content) == compute_checksum(test_file)


class TestSaveFile:
    def test_saves_file_to_correct_location(self, tmp_path: Path):
        content = b"file content"

        path, checksum = save_file(content, "Farm", "Turbine", "file.pdf", base_dir=tmp_path)

        assert path == tmp_path / "Farm" / "Turbine" / "file.pdf"
        assert path.read_bytes() == content
        assert checksum == compute_checksum_from_bytes(content)

    def test_creates_parent_directories(self, tmp_path: Path):
        content = b"content"

        path, _ = save_file(content, "New/Farm", "New/Turbine", "file.pdf", base_dir=tmp_path)

        assert path.exists()
        assert path.parent.exists()

    def test_handles_collision(self, tmp_path: Path):
        content1 = b"first"
        content2 = b"second"

        path1, _ = save_file(content1, "Farm", "Turbine", "file.pdf", base_dir=tmp_path)
        path2, _ = save_file(content2, "Farm", "Turbine", "file.pdf", base_dir=tmp_path)

        assert path1 != path2
        assert path2.name == "file_1.pdf"
        assert path1.read_bytes() == content1
        assert path2.read_bytes() == content2

    def test_overwrites_without_collision_handling(self, tmp_path: Path):
        content1 = b"first"
        content2 = b"second"

        path1, _ = save_file(content1, "Farm", "Turbine", "file.pdf", base_dir=tmp_path)
        path2, _ = save_file(
            content2, "Farm", "Turbine", "file.pdf", base_dir=tmp_path, handle_collision=False
        )

        assert path1 == path2
        assert path1.read_bytes() == content2
