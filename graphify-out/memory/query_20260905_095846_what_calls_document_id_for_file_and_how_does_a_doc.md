---
type: "query"
date: "2026-09-05T09:58:46.572091+00:00"
question: "What calls document_id_for_file and how does a document id flow through ingestion, PostgreSQL foreign keys, session attachments, and retrieval?"
contributor: "graphify"
source_nodes: ["document_id_for_file", "process_document", "ingest_bundle", "attach_documents_to_session", "hybrid_search_and_join"]
---

# Q: What calls document_id_for_file and how does a document id flow through ingestion, PostgreSQL foreign keys, session attachments, and retrieval?

## Answer

document_id_for_file is called before upload deduplication and by process_document. The ID becomes documents.id and doc_id on parents, children, figures, tables, and table_chunks; user_sessions.document_ids scopes retrieval. Content-only SHA-256 IDs therefore prevent identical uploads with different filenames from creating separate relational and vector hierarchies.

## Source Nodes

- document_id_for_file
- process_document
- ingest_bundle
- attach_documents_to_session
- hybrid_search_and_join