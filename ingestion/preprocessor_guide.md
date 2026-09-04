# Document Preprocessor Guide

## Purpose

`ingestion.doc_processor` is a standalone document-preprocessing service for the
RAG pipeline. It converts a local document into a normalized, retrieval-ready
bundle without requiring a vector database or an agent runtime.

It accepts files supported by Docling (including PDF, DOCX, and image inputs) and
returns:

- normalized document metadata;
- 2,000-token parent blocks;
- 250-token child chunks used for vector retrieval;
- figures with Gemini semantic captions and page-aware bounding boxes;
- canonical tables with native heading/caption context and row-safe table chunks;
- a validation manifest.

The service uses Docling for conversion/OCR, OcrMac on Apple Silicon for PDF OCR,
and Gemini through the OpenAI-compatible endpoint for document summaries and
figure captions. It does not use the Google native SDK, RapidOCR, PyPDF2, or
pypdf.

## Configuration

Set these variables in `.env`:

```dotenv
GEMINI_API_KEY=...
LLM_MODEL_NAME=gemini-3.5-flash-lite
```

`LLM_MODEL_NAME` is optional. Its default is `gemini-3.5-flash-lite`.

On macOS Apple Silicon, install dependencies with:

```bash
uv add "docling[ocrmac]" openai tiktoken
```

The PDF pipeline intentionally fails on unsupported systems instead of silently
switching OCR engines. The explicit error is:

```text
OcrMac is only supported on macOS with Apple Silicon. Run 'pip install docling[ocrmac]'
```

## Running the service

Call the public function directly from the repository root:

```bash
uv run --env-file .env python -c "
import json
from ingestion.doc_processor import process_document

result = process_document('dummy_data/ifc-annual-report-2024-financials.pdf')
print(json.dumps(result, indent=2))
"
```

For a durable output file, the calling application should serialize the returned
bundle to a JSON file next to the uploaded source. Do not run a script located
outside the repository unless `PYTHONPATH` includes the repository root.

## Data model and relationships

```text
document
  ├── parents[]
  │     ├── figure_ids[] ──> figures[]
  │     └── table_ids[]  ──> tables[]
  ├── children[]
  │     └── parent_id ─────> parents[]
  ├── figures[]
  ├── tables[]
  │     └── chunk_ids[] ───> table_chunks[]
  ├── table_chunks[]
  │     └── table_id ──────> tables[]
  └── validation
```

`parents` hold source content once. `children` do not duplicate parent text:
they carry a global document summary and a 250-token retrieval segment, then
resolve full context through `parent_id`.

Figures and tables are also stored once. A parent points to related figures with
`figure_ids` and tables with `table_ids`. This prevents duplicate visual/table
content in every child vector record.

## How to use the bundle in RAG

1. Embed and index `children[].text_with_context` for ordinary prose retrieval.
2. On a child hit, load its parent using `child.parent_id`.
3. Load every `figures` record identified by `parent.figure_ids`.
4. Load every `tables` record identified by `parent.table_ids` and, when needed,
   the referenced `table_chunks` for row-level evidence.
5. Give the LLM the child, full parent, and only the linked figure/table evidence.

Never answer from a child alone when the question may depend on a table or
figure. Do not independently embed every full parent, figure caption, and table
unless the retrieval design deliberately supports separate collections; doing so
creates redundant matches and can over-weight one source section.

## Native table context

For each `TableItem`, the preprocessor stores:

- `markdown`: canonical Docling table Markdown;
- `heading`: the nearest preceding Docling title or section heading;
- `caption`: the immediately preceding native caption, when Docling labels it;
- `context`: heading plus caption, or heading plus preceding text;
- `bounding_boxes`: source page coordinates;
- `row_count`, `column_count`, and `chunk_ids`.

Table chunks repeat native context and table headers, then add complete rows.
Rows are never split across a chunk boundary. This preserves the relationship
between a numeric value, its row label, its headers, and the section explaining
the table.

## Acceptance checks: is a processed item useful?

Run these checks before indexing a bundle. An item is useful only when it is
both structurally valid and faithful to the uploaded source.

### Bundle-level checks

- `validation.errors` must be empty.
- `remaining_image_placeholders` must be `0`.
- `figures_detected == figures_captioned == figures_with_bounding_boxes`.
- `tables_detected == tables_exported`.
- `figures_unassigned == 0` and `tables_unassigned == 0`.
- `tables_split_across_chunks == 0`.
- Every child `parent_id` must resolve to one parent.
- Every parent `figure_id` and `table_id` reference must resolve.

### Source-alignment checks

Sample content from every uploaded document, with extra samples for long PDFs:

1. **Prose:** compare a child and its parent with the source page. It must retain
   the section topic, entities, units, dates, qualifiers, and nearby conclusions.
2. **Figures:** compare the image, caption, and bounding box. The caption must
   describe the visible chart/diagram, not infer unsupported claims.
3. **Tables:** compare headers, a few random rows, totals, and units with the
   source PDF. Confirm that the saved heading/caption explains what the table
   represents.
4. **Cross-references:** ask retrieval questions whose answer requires a prose
   explanation plus a linked table or figure. The assembled RAG context must
   include both records.

The item is not suitable for production retrieval if it is structurally valid
but fails these source comparisons. Quarantine the document or the specific
table/figure instead of silently indexing unreliable evidence.

## Known limitations and operational safeguards

| Risk | Effect | Safeguard |
|---|---|---|
| Table grid matching drops cells | A table can be incomplete even when exported | Review Docling `MatchingPostProcessor` warnings; sample headers/rows against source pages; quarantine affected tables. |
| OcrMac has no page-empty OCR report | The manifest cannot identify OCR-empty pages | Compare native PDF text and OCR output during sampling; treat `ocr_validation_supported: false` as an explicit coverage gap. |
| A single table row exceeds 250 tokens | That row-safe chunk exceeds the child target | Store it as one exception and flag it; never split the row without a column-aware alternative. |
| Gemini calls run serially | Large documents are slower and cost more | Rate-limit and monitor calls; cache captions by source-image hash before adding concurrency. |
| Heading/caption may repeat | Retrieval context has harmless duplication | Deduplicate identical normalized strings before emitting `context`. |
| Gemini caption hallucination | Visual evidence can be misrepresented | Require the caption to describe only visible content; audit sampled captions against images. |

## Recommended release gate

Do not index an uploaded document until all of the following are true:

```text
validation.errors == []
figures_detected == figures_captioned == figures_with_bounding_boxes
tables_detected == tables_exported
figures_unassigned == 0
tables_unassigned == 0
remaining_image_placeholders == 0
tables_split_across_chunks == 0
```

Additionally, manually inspect sampled source-to-output mappings and at least
one RAG answer that requires both prose and a linked table or figure. This proves
the processed item is not merely parseable—it is useful, attributable, and
aligned with the uploaded document.
