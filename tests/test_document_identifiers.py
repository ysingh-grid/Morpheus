"""Document identifier contract coverage."""

from pathlib import Path

from ingestion.doc_processor import _document_id


def test_document_id_distinguishes_different_files_with_the_same_name(tmp_path: Path) -> None:
    """Prevent same-name uploads from replacing each other in PostgreSQL."""
    first_directory = tmp_path / "first"
    second_directory = tmp_path / "second"
    first_directory.mkdir()
    second_directory.mkdir()
    first_file = first_directory / "report.pdf"
    second_file = second_directory / "report.pdf"
    first_file.write_bytes(b"first report")
    second_file.write_bytes(b"second report")

    assert _document_id(first_file) != _document_id(second_file)


def test_document_id_matches_identical_content_under_different_names(tmp_path: Path) -> None:
    """Open WebUI filename prefixes cannot create duplicate document identities."""
    first_file = tmp_path / "report.pdf"
    second_file = tmp_path / "upload-uuid_report-renamed.pdf"
    first_file.write_bytes(b"identical report")
    second_file.write_bytes(b"identical report")

    assert _document_id(first_file) == _document_id(second_file)
    assert _document_id(first_file).startswith("sha256-")
