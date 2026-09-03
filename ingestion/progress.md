# Ingestion Progress

## Completed

- Configured a global OpenAI-compatible Gemini client in `core/config.py`.
- Implemented Docling conversion, document summaries, hierarchical parent/child chunks, and figure metadata in `ingestion/doc_processor.py`.
- Added detailed ingestion lifecycle logging.
- Enabled Docling PDF page and picture image generation.
- Configured RapidOCR to use its Torch MPS backend.
- Added a live Docling and Gemini integration test; it passes when `GEMINI_API_KEY` is loaded from `.env`.
- Added project dependencies with uv and generated the Graphify code graph.

## Missing

- Re-run the full IFC annual-report extraction after the image-generation and RapidOCR MPS configuration changes.
- Verify that the regenerated output contains figure captions and bounding boxes.
- Persist the extraction runner in the repository; the current runner is temporary and located in `/private/tmp`.

## Known Issues

- The existing annual-report chunk JSON was created before PDF image generation was enabled, so it contains no figure captions or bounding boxes.
- RapidOCR on MPS emits an Objective-C `MPSGraph` weak-reference warning and a leaked-semaphore warning during shutdown; its stability is not yet established.
- RapidOCR reports empty text detection for some pages or regions. Conversion continues, but those regions may have reduced OCR quality.
- Gemini was asked for a 50-word summary but returned 63 words; summary length is not currently enforced.
