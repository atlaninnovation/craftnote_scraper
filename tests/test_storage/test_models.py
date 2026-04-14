from craftnote_scraper.storage.models import FileType


class TestFileType:
    def test_from_filename_pdf(self):
        assert FileType.from_filename("report.pdf") == FileType.PDF

    def test_from_filename_xlsx(self):
        assert FileType.from_filename("data.xlsx") == FileType.XLSX

    def test_from_filename_xls(self):
        assert FileType.from_filename("legacy.xls") == FileType.XLS

    def test_from_filename_uppercase(self):
        assert FileType.from_filename("REPORT.PDF") == FileType.PDF

    def test_from_filename_unknown(self):
        assert FileType.from_filename("image.png") == FileType.UNKNOWN

    def test_from_filename_no_extension(self):
        assert FileType.from_filename("noextension") == FileType.UNKNOWN
