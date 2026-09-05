# Ingestion Progress

## Completed

- Configured a global OpenAI-compatible Gemini client in `core/config.py`.
- Implemented Docling conversion, document summaries, hierarchical parent/child chunks, and figure metadata in `ingestion/doc_processor.py`.
- Normalized parent storage: each 2,000-token parent block is stored once and children reference it by `parent_id`.
- Normalized figure storage: figures are stored once and relevant parents reference them by `figure_ids`.
- Normalized table storage: each table is stored once with its canonical Markdown, native Docling heading/caption context, bounding boxes, and row-safe retrieval chunks.
- Replaced table Markdown in parent content with stable `table_id` references, so each parent links to relevant tables through `table_ids`.
- Added a per-document validation manifest for figure/table coverage, parent assignment, placeholder removal, and table row-boundary safety.
- Added `preprocessor_guide.md`, documenting the standalone service architecture, RAG joins, acceptance checks, source-alignment review, and operational safeguards.
- Added Phase 2 PostgreSQL/pgvector retrieval storage: normalized relational schema, HNSW child-vector index, full-text index, atomic bundle loader, and a single-query RRF retrieval join.
- Added Gemini `gemini-embedding-001` embeddings at the fixed pgvector dimension of 1,536 and CPU-compatible FlashRank reranking.
- Added detailed ingestion lifecycle logging.
- Enabled Docling PDF page and picture image generation.
- Replaced RapidOCR with native Apple Silicon OcrMac; unsupported environments now fail explicitly instead of silently changing OCR engines.
- Added a live Docling and Gemini integration test; it passes when `GEMINI_API_KEY` is loaded from `.env`.
- Added project dependencies with uv and generated the Graphify code graph.
- Regenerated the IFC annual-report bundle successfully: 35 captioned/bounded figures, 156 tables, 648 table chunks, and no validation errors.
- Preserved page provenance through page-aware Markdown export; parents, children, and table chunks now carry explicit `page_numbers` arrays.

## Missing

- Re-run the full IFC annual-report extraction to generate the new `tables`, `table_chunks`, and `validation` output sections.
- Verify that the regenerated output contains complete figure/table coverage and no validation errors.
- Persist the extraction runner in the repository; the current runner is temporary and located in `/private/tmp`.
- Configure a PostgreSQL database with the pgvector extension and set `DATABASE_URL`, then run an end-to-end schema/ingest/retrieval test.
- Deduplicate table context when the nearest preceding text is identical to the detected heading.
- Flag tables that Docling reports as having dropped or heuristically recovered cells for manual source review.

## Known Issues

- Downstream RAG code must resolve each child through `parent_id` and attach the parent's `figure_ids` and `table_ids`; querying children alone omits normalized visual/table evidence.
- Page-level OCR-empty-page detection is not exposed by the configured OcrMac pipeline. The manifest reports this limitation as a warning rather than fabricating page results.
- Docling table matching can recover cells by nearest row/column or drop unmatched cells. A table can therefore pass structural validation while still needing source-level cell accuracy review.
- Gemini was asked for a 50-word summary but returned 63 words; summary length is not currently enforced.
- Bundles created before page provenance was added must be reprocessed before answers can cite their pages.
