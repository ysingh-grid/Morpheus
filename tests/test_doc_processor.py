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
        pytest.skip("Set GEMINI_API_KEY to run the live Docling and Gemini integration test.")
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
    document.save(source_document)

    from ingestion.doc_processor import process_document

    chunks = process_document(str(source_document))

    assert chunks
    required_keys = {"chunk_id", "parent_id", "text_with_context", "parent_text", "metadata"}
    for chunk in chunks:
        assert set(chunk) == required_keys
        assert chunk["text_with_context"].startswith("Document summary:")
        assert chunk["chunk_id"].startswith("quarterly_growth_report-parent-")
        assert chunk["parent_id"] in chunk["chunk_id"]

    figures = chunks[0]["metadata"]["figures"]
    assert figures
    assert figures[0]["caption"]
    assert isinstance(figures[0]["bounding_boxes"], list)
