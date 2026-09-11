---
type: "query"
date: "2026-09-07T05:19:26.850301+00:00"
question: "How does durable PDF ingestion flow from the FastAPI gateway through Temporal to PostgreSQL?"
contributor: "graphify"
source_nodes: ["DocumentIngestionWorkflow.run(),DocumentIngestionWorkflow.get_ingestion_progress(),hash_and_deduplicate_document_activity(),parse_docling_layout_activity(),generate_embeddings_activity(),commit_document_bundle_activity(),start_document_upload_job(),get_document_upload_job()"]
---

# Q: How does durable PDF ingestion flow from the FastAPI gateway through Temporal to PostgreSQL?

## Answer

The gateway stores one PDF, starts DocumentIngestionWorkflow, and polls its queryable progress instead of retaining in-memory job state. The workflow hashes and deduplicates, invokes Docling with page-layout heartbeats, generates retrying Gemini embeddings, commits the normalized bundle atomically through pgvector, and attaches the document to the chat session. A retried parse occurs before the single commit boundary, preventing duplicate parents and children.

## Source Nodes

- DocumentIngestionWorkflow.run(),DocumentIngestionWorkflow.get_ingestion_progress(),hash_and_deduplicate_document_activity(),parse_docling_layout_activity(),generate_embeddings_activity(),commit_document_bundle_activity(),start_document_upload_job(),get_document_upload_job()