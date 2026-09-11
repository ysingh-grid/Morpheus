---
type: "query"
date: "2026-09-07T08:58:35.371366+00:00"
question: "How does the ingestion workflow avoid Temporal payload limits while supporting multi-PDF uploads?"
contributor: "graphify"
source_nodes: ["DocumentIngestionWorkflow.run(),parse_docling_layout_activity(),generate_embeddings_activity(),commit_document_bundle_activity(),start_document_upload_job(),get_document_upload_job(),_aggregate_ingestion_progress()"]
---

# Q: How does the ingestion workflow avoid Temporal payload limits while supporting multi-PDF uploads?

## Answer

DocumentIngestionWorkflow passes only staging-file references between parse, embedding, and commit activities; raw Docling bundles and vectors never enter workflow history. The gateway starts one deterministic child workflow per PDF and returns a stateless batch identifier that encodes child workflow IDs for aggregated progress polling. Duplicate starts reuse the active workflow, while the macOS parsing activity serializes OcrMac with a worker mutex.

## Source Nodes

- DocumentIngestionWorkflow.run(),parse_docling_layout_activity(),generate_embeddings_activity(),commit_document_bundle_activity(),start_document_upload_job(),get_document_upload_job(),_aggregate_ingestion_progress()