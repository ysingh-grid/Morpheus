"""Convert local documents into context-rich chunks for retrieval."""

import base64
import logging
from io import BytesIO
from pathlib import Path
from typing import List, TypedDict

import tiktoken
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc import PictureItem

from core.config import DEFAULT_MODEL, llm_client


logger = logging.getLogger(__name__)

PARENT_TOKEN_LIMIT = 2_000
CHILD_TOKEN_LIMIT = 250
SUMMARY_WORD_LIMIT = 50
IMAGE_PLACEHOLDER = "<!-- image -->"


class ProcessedChunk(TypedDict):
    """A retrieval child chunk with its parent context and document metadata."""

    chunk_id: str
    parent_id: str
    text_with_context: str
    parent_text: str
    metadata: dict[str, object]


def _encoding() -> tiktoken.Encoding:
    """Return the tokenizer used to enforce stable chunk-size boundaries."""
    return tiktoken.get_encoding("cl100k_base")


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


def _figure_metadata(document: object) -> list[dict[str, object]]:
    """Caption each extracted figure and retain its page-level bounding boxes."""
    figures: list[dict[str, object]] = []
    logger.info("Scanning Docling document for figures")
    for item, _ in document.iterate_items(traverse_pictures=True):
        if not isinstance(item, PictureItem):
            continue

        image = item.get_image(document)
        if image is None:
            logger.warning("Skipping figure because Docling did not provide image data")
            continue

        bounding_boxes = [
            {
                "page_no": provenance.page_no,
                "bbox": provenance.bbox.model_dump(mode="json"),
            }
            for provenance in item.prov
        ]
        figures.append(
            {
                "caption": _caption_image(image),
                "bounding_boxes": bounding_boxes,
            }
        )
        logger.info("Processed figure", extra={"figure_count": len(figures), "bounding_box_count": len(bounding_boxes)})
    logger.info("Completed figure extraction", extra={"figure_count": len(figures)})
    return figures


def _replace_image_placeholders(markdown: str, figures: list[dict[str, object]]) -> str:
    """Replace Docling's image placeholders with the generated figure captions."""
    placeholders = markdown.count(IMAGE_PLACEHOLDER)
    logger.info(
        "Replacing image placeholders",
        extra={"placeholder_count": placeholders, "caption_count": len(figures)},
    )
    for figure in figures:
        caption = str(figure["caption"])
        markdown = markdown.replace(IMAGE_PLACEHOLDER, f"\n\n[Figure: {caption}]\n\n", 1)
    return markdown


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


def process_document(file_path: str) -> List[dict]:
    """Convert one local document into hierarchical, retrieval-ready child chunks.

    Args:
        file_path: Path to a PDF, DOCX file, or supported image document.

    Returns:
        Child chunks linked to their 2,000-token parent block, with the document
        summary prepended to each child's retrieval text.
    """
    source_path = Path(file_path)
    logger.info(
        "Starting document ingestion",
        extra={"source_path": str(source_path), "source_bytes": source_path.stat().st_size},
    )
    pdf_pipeline_options = PdfPipelineOptions()
    pdf_pipeline_options.generate_page_images = True
    pdf_pipeline_options.generate_picture_images = True
    pdf_pipeline_options.ocr_options = RapidOcrOptions(
        backend="torch",
        rapidocr_params={"EngineConfig.torch.use_mps": True},
    )
    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_pipeline_options),
        }
    )
    logger.info("Enabled Docling PDF image generation and RapidOCR MPS")
    conversion = converter.convert(source_path)
    document = conversion.document
    logger.info("Docling conversion completed", extra={"source_path": str(source_path)})
    figures = _figure_metadata(document)
    markdown = document.export_to_markdown(
        image_placeholder=IMAGE_PLACEHOLDER,
        traverse_pictures=True,
    )
    logger.info("Exported Docling document to Markdown", extra={"markdown_characters": len(markdown)})
    markdown = _replace_image_placeholders(markdown, figures)
    summary = _summarize_document(markdown)

    chunks: list[ProcessedChunk] = []
    parent_blocks = _split_tokens(markdown, PARENT_TOKEN_LIMIT)
    logger.info("Created parent blocks", extra={"parent_count": len(parent_blocks)})
    for parent_index, parent_text in enumerate(parent_blocks):
        parent_id = f"{source_path.stem}-parent-{parent_index}"
        for child_index, child_text in enumerate(_split_tokens(parent_text, CHILD_TOKEN_LIMIT)):
            chunks.append(
                {
                    "chunk_id": f"{parent_id}-child-{child_index}",
                    "parent_id": parent_id,
                    "text_with_context": f"Document summary: {summary}\n\n{child_text}",
                    "parent_text": parent_text,
                    "metadata": {
                        "source_path": str(source_path),
                        "figures": figures,
                    },
                }
            )
    logger.info(
        "Completed document ingestion",
        extra={"source_path": str(source_path), "parent_count": len(parent_blocks), "child_count": len(chunks)},
    )
    return chunks
