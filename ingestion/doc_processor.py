"""Convert local documents into context-rich chunks for retrieval."""

import base64
import hashlib
import importlib.util
import logging
import platform
import re
from io import BytesIO
from pathlib import Path
from typing import TypedDict

import tiktoken
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import OcrMacOptions, PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc import DocItemLabel, PictureItem, TableItem, TextItem

from core.config import DEFAULT_MODEL, llm_client


logger = logging.getLogger(__name__)

PARENT_TOKEN_LIMIT = 2_000
CHILD_TOKEN_LIMIT = 250
SUMMARY_WORD_LIMIT = 50
IMAGE_PLACEHOLDER = "<!-- image -->"
FIGURE_REFERENCE_PATTERN = re.compile(r"\[Figure (figure-\d{3}):")
TABLE_REFERENCE_PATTERN = re.compile(r"\[Table (table-\d{3})\]")


class ProcessedChunk(TypedDict):
    """A retrieval child chunk linked to normalized parent content."""

    chunk_id: str
    parent_id: str
    text_with_context: str
    metadata: dict[str, object]


class ParentBlock(TypedDict):
    """One normalized 2,000-token parent block."""

    parent_id: str
    parent_text: str
    figure_ids: list[str]
    table_ids: list[str]


class Figure(TypedDict):
    """One captioned figure and its source-document coordinates."""

    figure_id: str
    caption: str
    bounding_boxes: list[dict[str, object]]


class DocumentMetadata(TypedDict):
    """Document-level metadata shared by its parents, children, and figures."""

    document_id: str
    source_path: str
    summary: str


class TableChunk(TypedDict):
    """A row-safe retrieval representation of a canonical table."""

    table_chunk_id: str
    table_id: str
    row_start: int
    row_end: int
    text_with_context: str


class TableRecord(TypedDict):
    """One canonical table with native Docling context and retrieval chunks."""

    table_id: str
    markdown: str
    heading: str
    caption: str
    context: str
    bounding_boxes: list[dict[str, object]]
    row_count: int
    column_count: int
    chunk_ids: list[str]


class ValidationManifest(TypedDict):
    """Coverage and integrity checks for one normalized document bundle."""

    pages: int
    text_items: int
    tables_detected: int
    tables_exported: int
    tables_unassigned: int
    figures_detected: int
    figures_captioned: int
    figures_with_bounding_boxes: int
    figures_unassigned: int
    remaining_image_placeholders: int
    ocr_empty_pages: list[int]
    ocr_validation_supported: bool
    tables_split_across_chunks: int
    errors: list[str]
    warnings: list[str]


class ProcessedDocument(TypedDict):
    """Normalized parent and child records produced from one source document."""

    document: DocumentMetadata
    figures: list[Figure]
    tables: list[TableRecord]
    table_chunks: list[TableChunk]
    parents: list[ParentBlock]
    children: list[ProcessedChunk]
    validation: ValidationManifest


def _encoding() -> tiktoken.Encoding:
    """Return the tokenizer used to enforce stable chunk-size boundaries."""
    return tiktoken.get_encoding("cl100k_base")


def document_id_for_file(file_path: str | Path) -> str:
    """Return the stable content-aware identifier used by ingestion and upload deduplication."""
    source_path = Path(file_path)
    content_hash = hashlib.sha256()
    with source_path.open("rb") as source_file:
        for block in iter(lambda: source_file.read(1_048_576), b""):
            content_hash.update(block)
    return f"{source_path.stem}-{content_hash.hexdigest()[:16]}"


def _document_id(source_path: Path) -> str:
    """Retain the existing private identifier helper for compatibility."""
    return document_id_for_file(source_path)


def _ocrmac_options() -> OcrMacOptions:
    """Return native Apple OCR options or raise a clear unsupported-platform error."""
    if platform.system() != "Darwin" or platform.machine() not in {"arm64", "aarch64"}:
        raise RuntimeError(
            "OcrMac is only supported on macOS with Apple Silicon. "
            "Run 'pip install docling[ocrmac]'"
        )
    if importlib.util.find_spec("ocrmac") is None:
        raise RuntimeError(
            "OcrMac is only supported on macOS with Apple Silicon. "
            "Run 'pip install docling[ocrmac]'"
        )
    try:
        return OcrMacOptions()
    except (OSError, RuntimeError, ValueError) as error:
        raise RuntimeError(
            "OcrMac is only supported on macOS with Apple Silicon. "
            "Run 'pip install docling[ocrmac]'"
        ) from error


def _caption_image(image: object) -> str:
    """Generate a dense semantic caption for a Docling-extracted image."""
    logger.info("Requesting semantic caption for extracted figure", extra={"image_size": getattr(image, "size", None)})
    image_buffer = BytesIO()
    image.save(image_buffer, format="PNG")
    image_data = base64.b64encode(image_buffer.getvalue()).decode("ascii")

    response = llm_client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Write a dense semantic caption for this document figure. "
                            "Include its subject, labels, relationships, values, and any "
                            "conclusion it communicates."
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image_data}"},
                    },
                ],
            }
        ],
    )
    caption = response.choices[0].message.content.strip()
    logger.info("Received semantic figure caption", extra={"caption_characters": len(caption)})
    return caption


def _bounding_boxes(item: object) -> list[dict[str, object]]:
    """Return page-aware bounding boxes from a Docling item."""
    return [
        {
            "page_no": provenance.page_no,
            "bbox": provenance.bbox.model_dump(mode="json"),
        }
        for provenance in item.prov
    ]


def _figure_metadata(document: object) -> tuple[list[Figure], int]:
    """Caption each extracted figure and retain its page-level bounding boxes."""
    figures: list[Figure] = []
    detected_figures = 0
    logger.info("Scanning Docling document for figures")
    for item, _ in document.iterate_items(traverse_pictures=True):
        if not isinstance(item, PictureItem):
            continue

        detected_figures += 1
        image = item.get_image(document)
        if image is None:
            logger.warning("Skipping figure because Docling did not provide image data")
            continue

        bounding_boxes = _bounding_boxes(item)
        figures.append(
            {
                "figure_id": f"figure-{len(figures) + 1:03d}",
                "caption": _caption_image(image),
                "bounding_boxes": bounding_boxes,
            }
        )
        logger.info("Processed figure", extra={"figure_count": len(figures), "bounding_box_count": len(bounding_boxes)})
    logger.info(
        "Completed figure extraction",
        extra={"detected_figure_count": detected_figures, "captioned_figure_count": len(figures)},
    )
    return figures, detected_figures


def _table_rows(table: TableItem) -> tuple[list[str], list[tuple[int, str]]]:
    """Create a header and row-safe textual representation from Docling table cells."""
    row_count = table.data.num_rows
    column_count = table.data.num_cols
    rows = [["" for _ in range(column_count)] for _ in range(row_count)]
    header_rows: set[int] = set()

    for cell in table.data.table_cells:
        for row_index in range(cell.start_row_offset_idx, cell.end_row_offset_idx):
            for column_index in range(cell.start_col_offset_idx, cell.end_col_offset_idx):
                if not rows[row_index][column_index]:
                    rows[row_index][column_index] = cell.text
            if cell.column_header:
                header_rows.add(row_index)

    header = [" | ".join(rows[row_index]) for row_index in sorted(header_rows)]
    data_rows = [
        (row_index + 1, " | ".join(row))
        for row_index, row in enumerate(rows)
        if row_index not in header_rows
    ]
    return header, data_rows


def _table_chunk_records(table_id: str, table: TableItem, context: str) -> list[TableChunk]:
    """Create token-bounded table chunks without splitting a table row."""
    header_rows, data_rows = _table_rows(table)
    header_text = "\n".join(f"Headers: {row}" for row in header_rows)
    prefix = "\n".join(part for part in (context, header_text) if part)
    encoding = _encoding()
    chunks: list[TableChunk] = []
    current_rows: list[tuple[int, str]] = []

    def append_chunk(rows: list[tuple[int, str]]) -> None:
        if not rows:
            return
        chunk_index = len(chunks)
        row_text = "\n".join(f"Row {row_index}: {row}" for row_index, row in rows)
        chunks.append(
            {
                "table_chunk_id": f"{table_id}-chunk-{chunk_index}",
                "table_id": table_id,
                "row_start": rows[0][0],
                "row_end": rows[-1][0],
                "text_with_context": "\n".join(part for part in (prefix, row_text) if part),
            }
        )

    for row in data_rows:
        candidate_rows = [*current_rows, row]
        candidate_text = "\n".join(
            part
            for part in (
                prefix,
                "\n".join(f"Row {row_index}: {row_text}" for row_index, row_text in candidate_rows),
            )
            if part
        )
        if current_rows and len(encoding.encode(candidate_text)) > CHILD_TOKEN_LIMIT:
            append_chunk(current_rows)
            current_rows = [row]
        else:
            current_rows = candidate_rows
    append_chunk(current_rows)

    if not chunks:
        chunks.append(
            {
                "table_chunk_id": f"{table_id}-chunk-0",
                "table_id": table_id,
                "row_start": 0,
                "row_end": 0,
                "text_with_context": prefix,
            }
        )
    return chunks


def _table_metadata(document: object) -> tuple[list[TableRecord], list[TableChunk], int]:
    """Extract canonical tables with native heading and caption context."""
    tables: list[TableRecord] = []
    table_chunks: list[TableChunk] = []
    detected_tables = 0
    current_heading = ""
    previous_text = ""
    previous_label: DocItemLabel | None = None

    for item, _ in document.iterate_items(traverse_pictures=True):
        if isinstance(item, TextItem):
            if item.label in {DocItemLabel.SECTION_HEADER, DocItemLabel.TITLE}:
                current_heading = item.text
            previous_text = item.text
            previous_label = item.label
            continue
        if not isinstance(item, TableItem):
            continue

        detected_tables += 1
        table_id = f"table-{detected_tables:03d}"
        caption = previous_text if previous_label == DocItemLabel.CAPTION else ""
        context_parts = [current_heading, caption]
        if not caption and previous_text:
            context_parts.append(previous_text)
        context = "\n".join(part for part in context_parts if part)
        record_chunks = _table_chunk_records(table_id, item, context)
        table_chunks.extend(record_chunks)
        tables.append(
            {
                "table_id": table_id,
                "markdown": item.export_to_markdown(document),
                "heading": current_heading,
                "caption": caption,
                "context": context,
                "bounding_boxes": _bounding_boxes(item),
                "row_count": item.data.num_rows,
                "column_count": item.data.num_cols,
                "chunk_ids": [chunk["table_chunk_id"] for chunk in record_chunks],
            }
        )

    logger.info(
        "Completed table extraction",
        extra={"detected_table_count": detected_tables, "table_chunk_count": len(table_chunks)},
    )
    return tables, table_chunks, detected_tables


def _replace_image_placeholders(markdown: str, figures: list[Figure]) -> str:
    """Replace Docling's image placeholders with the generated figure captions."""
    placeholders = markdown.count(IMAGE_PLACEHOLDER)
    logger.info(
        "Replacing image placeholders",
        extra={"placeholder_count": placeholders, "caption_count": len(figures)},
    )
    for figure in figures:
        caption = str(figure["caption"])
        markdown = markdown.replace(
            IMAGE_PLACEHOLDER,
            f"\n\n[Figure {figure['figure_id']}: {caption}]\n\n",
            1,
        )
    return markdown


def _replace_table_markdown(markdown: str, tables: list[TableRecord]) -> str:
    """Replace canonical tables in document Markdown with stable table references."""
    for table in tables:
        table_markdown = table["markdown"]
        if table_markdown not in markdown:
            logger.warning("Could not place table reference in Markdown", extra={"table_id": table["table_id"]})
            continue
        markdown = markdown.replace(table_markdown, f"\n\n[Table {table['table_id']}]\n\n", 1)
    return markdown


def _figure_ids_in_parent(parent_text: str) -> list[str]:
    """Return the unique figure IDs referenced by one parent block."""
    return list(dict.fromkeys(FIGURE_REFERENCE_PATTERN.findall(parent_text)))


def _table_ids_in_parent(parent_text: str) -> list[str]:
    """Return the unique table IDs referenced by one parent block."""
    return list(dict.fromkeys(TABLE_REFERENCE_PATTERN.findall(parent_text)))


def _validation_manifest(
    document: object,
    figures: list[Figure],
    detected_figures: int,
    tables: list[TableRecord],
    detected_tables: int,
    parents: list[ParentBlock],
    markdown: str,
) -> ValidationManifest:
    """Build integrity results and fail-fast errors for the normalized document bundle."""
    assigned_figures = {figure_id for parent in parents for figure_id in parent["figure_ids"]}
    unassigned_figures = {figure["figure_id"] for figure in figures} - assigned_figures
    assigned_tables = {table_id for parent in parents for table_id in parent["table_ids"]}
    unassigned_tables = {table["table_id"] for table in tables} - assigned_tables
    remaining_placeholders = markdown.count(IMAGE_PLACEHOLDER)
    errors: list[str] = []
    warnings: list[str] = []

    if detected_figures != len(figures):
        errors.append("Detected figures and captioned figures do not match.")
    if remaining_placeholders:
        errors.append("Raw image placeholders remain in document Markdown.")
    if unassigned_figures:
        errors.append("One or more captioned figures are not linked to a parent block.")
    if detected_tables != len(tables):
        warnings.append("Detected tables and exported tables do not match.")
    if unassigned_tables:
        warnings.append("One or more tables are not linked to a parent block.")
    if any(not table["chunk_ids"] for table in tables):
        warnings.append("One or more tables have no row-safe retrieval chunks.")
    warnings.append("Page-level OCR emptiness is not exposed by the configured OcrMac pipeline.")

    return {
        "pages": len(document.pages),
        "text_items": sum(
            1 for item, _ in document.iterate_items(traverse_pictures=True) if isinstance(item, TextItem)
        ),
        "tables_detected": detected_tables,
        "tables_exported": len(tables),
        "tables_unassigned": len(unassigned_tables),
        "figures_detected": detected_figures,
        "figures_captioned": len(figures),
        "figures_with_bounding_boxes": sum(bool(figure["bounding_boxes"]) for figure in figures),
        "figures_unassigned": len(unassigned_figures),
        "remaining_image_placeholders": remaining_placeholders,
        "ocr_empty_pages": [],
        "ocr_validation_supported": False,
        "tables_split_across_chunks": 0,
        "errors": errors,
        "warnings": warnings,
    }


def _summarize_document(markdown: str) -> str:
    """Create the required concise, global context for every retrieval chunk."""
    logger.info("Requesting global document summary", extra={"markdown_characters": len(markdown)})
    response = llm_client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Summarize this document in exactly {SUMMARY_WORD_LIMIT} words. "
                    "Preserve its main subject, conclusions, and important entities.\n\n"
                    f"{markdown}"
                ),
            }
        ],
    )
    summary = response.choices[0].message.content.strip()
    logger.info(
        "Received global document summary",
        extra={"summary_characters": len(summary), "summary_words": len(summary.split())},
    )
    return summary


def _split_tokens(text: str, limit: int) -> list[str]:
    """Split text into bounded token groups without discarding content."""
    encoding = _encoding()
    tokens = encoding.encode(text)
    chunks = [encoding.decode(tokens[index : index + limit]) for index in range(0, len(tokens), limit)]
    logger.debug("Split text into token-bounded chunks", extra={"token_count": len(tokens), "chunk_count": len(chunks), "token_limit": limit})
    return chunks


def process_document(file_path: str) -> ProcessedDocument:
    """Convert one local document into normalized parent and child retrieval records.

    Args:
        file_path: Path to a PDF, DOCX file, or supported image document.

    Returns:
        Parent blocks stored once, plus child chunks linked by ``parent_id`` with
        the document summary prepended to each child's retrieval text.
    """
    source_path = Path(file_path)
    logger.info(
        "Starting document ingestion",
        extra={"source_path": str(source_path), "source_bytes": source_path.stat().st_size},
    )
    pdf_pipeline_options = PdfPipelineOptions()
    pdf_pipeline_options.do_ocr = True
    pdf_pipeline_options.generate_page_images = True
    pdf_pipeline_options.generate_picture_images = True
    pdf_pipeline_options.ocr_options = _ocrmac_options()
    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_pipeline_options),
        }
    )
    logger.info("Enabled Docling PDF image generation and native OcrMac")
    conversion = converter.convert(source_path)
    document = conversion.document
    logger.info("Docling conversion completed", extra={"source_path": str(source_path)})
    figures, detected_figures = _figure_metadata(document)
    tables, table_chunks, detected_tables = _table_metadata(document)
    markdown = document.export_to_markdown(
        image_placeholder=IMAGE_PLACEHOLDER,
        traverse_pictures=True,
    )
    logger.info("Exported Docling document to Markdown", extra={"markdown_characters": len(markdown)})
    markdown = _replace_image_placeholders(markdown, figures)
    markdown = _replace_table_markdown(markdown, tables)
    summary = _summarize_document(markdown)
    document_id = document_id_for_file(source_path)

    chunks: list[ProcessedChunk] = []
    parents: list[ParentBlock] = []
    parent_blocks = _split_tokens(markdown, PARENT_TOKEN_LIMIT)
    logger.info("Created parent blocks", extra={"parent_count": len(parent_blocks)})
    for parent_index, parent_text in enumerate(parent_blocks):
        parent_id = f"{document_id}-parent-{parent_index}"
        parents.append(
            {
                "parent_id": parent_id,
                "parent_text": parent_text,
                "figure_ids": _figure_ids_in_parent(parent_text),
                "table_ids": _table_ids_in_parent(parent_text),
            }
        )
        for child_index, child_text in enumerate(_split_tokens(parent_text, CHILD_TOKEN_LIMIT)):
            chunks.append(
                {
                    "chunk_id": f"{parent_id}-child-{child_index}",
                    "parent_id": parent_id,
                    "text_with_context": f"Document summary: {summary}\n\n{child_text}",
                    "metadata": {"document_id": document_id},
            }
        )
    validation = _validation_manifest(
        document=document,
        figures=figures,
        detected_figures=detected_figures,
        tables=tables,
        detected_tables=detected_tables,
        parents=parents,
        markdown=markdown,
    )
    if validation["errors"]:
        logger.error("Document validation failed", extra={"errors": validation["errors"]})
        raise RuntimeError("Document validation failed: " + " ".join(validation["errors"]))
    if validation["warnings"]:
        logger.warning("Document validation warnings", extra={"warnings": validation["warnings"]})
    logger.info(
        "Completed document ingestion",
        extra={"source_path": str(source_path), "parent_count": len(parents), "child_count": len(chunks)},
    )
    logger.info("DOCUMENT INGESTION COMPLETE")
    return {
        "document": {
            "document_id": document_id,
            "source_path": str(source_path),
            "summary": summary,
        },
        "figures": figures,
        "tables": tables,
        "table_chunks": table_chunks,
        "parents": parents,
        "children": chunks,
        "validation": validation,
    }
