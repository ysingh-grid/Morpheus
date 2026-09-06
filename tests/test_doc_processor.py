"""Live integration coverage for document ingestion."""

import os
from pathlib import Path

import pytest
from docx import Document
from docx.shared import Inches
from PIL import Image, ImageDraw


@pytest.fixture
def gemini_api_key() -> str:
    """Require credentials because this test sends a real Gemini request."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        pytest.skip(
            "Set GEMINI_API_KEY to run the live Docling and Gemini integration test."
        )
    return api_key


def test_process_document_with_real_docling_and_gemini(
    tmp_path: Path,
    gemini_api_key: str,
) -> None:
    """Process a real local image with Docling and Gemini, without mocks."""
    del gemini_api_key
    source_image = tmp_path / "quarterly_growth.png"
    image = Image.new("RGB", (480, 240), color="white")
    drawing = ImageDraw.Draw(image)
    drawing.text((30, 40), "Quarterly revenue growth", fill="black")
    drawing.text((30, 100), "Q3: 15%", fill="black")
    image.save(source_image)

    source_document = tmp_path / "quarterly_growth_report.docx"
    document = Document()
    document.add_heading("Quarterly Revenue Report", level=1)
    document.add_paragraph("The embedded figure shows third-quarter revenue growth.")
    document.add_picture(str(source_image), width=Inches(2.0))
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Quarter"
    table.cell(0, 1).text = "Growth"
    table.cell(1, 0).text = "Q3"
    table.cell(1, 1).text = "15%"
    document.save(source_document)

    from ingestion.doc_processor import process_document

    progress_events: list[tuple[int, str, dict[str, object]]] = []
    result = process_document(
        str(source_document),
        progress_callback=lambda percent, stage, details: progress_events.append(
            (percent, stage, details)
        ),
    )
    document_metadata = result["document"]
    figures = result["figures"]
    tables = result["tables"]
    table_chunks = result["table_chunks"]
    parents = result["parents"]
    chunks = result["children"]
    validation = result["validation"]

    assert chunks
    assert parents
    assert document_metadata["document_id"].startswith("sha256-")
    assert document_metadata["content_sha256"] == document_metadata[
        "document_id"
    ].removeprefix("sha256-")
    assert figures
    figure_ids = {figure["figure_id"] for figure in figures}
    assert all(figure["caption"] for figure in figures)
    assert all(isinstance(figure["bounding_boxes"], list) for figure in figures)
    assert tables
    assert table_chunks
    table_ids = {table["table_id"] for table in tables}
    assert all(table["chunk_ids"] for table in tables)
    assert all(chunk["table_id"] in table_ids for chunk in table_chunks)
    assert all(chunk["page_numbers"] for chunk in table_chunks)
    parent_ids = {parent["parent_id"] for parent in parents}
    assert all("parent_text" in parent for parent in parents)
    assert all(parent["page_numbers"] for parent in parents)
    assert all(set(parent["figure_ids"]) <= figure_ids for parent in parents)
    assert all(set(parent["table_ids"]) <= table_ids for parent in parents)
    assert any(parent["figure_ids"] for parent in parents)
    assert any(parent["table_ids"] for parent in parents)
    assert validation["errors"] == []
    assert validation["tables_detected"] == validation["tables_exported"]
    assert progress_events[0][:2] == (0, "starting_preprocessing")
    assert progress_events[-1][:2] == (100, "preprocessing_complete")
    assert any(stage == "captioning_figures" for _, stage, _ in progress_events)
    required_keys = {"chunk_id", "parent_id", "text_with_context", "metadata"}
    for chunk in chunks:
        assert set(chunk) == required_keys
        assert chunk["text_with_context"].startswith("Document summary:")
        assert chunk["chunk_id"].startswith(
            f"{document_metadata['document_id']}-parent-"
        )
        assert chunk["parent_id"] in parent_ids
        assert chunk["metadata"]["document_id"] == document_metadata["document_id"]
        assert chunk["metadata"]["page_numbers"]


def test_page_token_stream_preserves_pages_across_chunk_boundaries() -> None:
    """Token slicing retains exact page sets when one page crosses a chunk boundary."""
    from ingestion.doc_processor import _decode_page_chunk, _page_token_stream

    stream = _page_token_stream(
        [
            (1, "first-page-content " * 400),
            (2, "second-page-content " * 20),
        ]
    )
    chunks = [stream[index : index + 250] for index in range(0, len(stream), 250)]
    decoded = [_decode_page_chunk(chunk) for chunk in chunks]

    assert decoded[0][1] == [1]
    assert decoded[-1][1][-1] == 2
    assert set(page for _, pages in decoded for page in pages) == {1, 2}
