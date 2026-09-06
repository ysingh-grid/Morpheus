---
type: "query"
date: "2026-09-05T09:27:12.697233+00:00"
question: "Why does the first IFC document overview query fail while later questions improve?"
contributor: "graphify"
source_nodes: ["_scope_document_query()", "hybrid_search_and_join()", "_assess_confidence()", "persist_session_turn_activity()"]
---

# Q: Why does the first IFC document overview query fail while later questions improve?

## Answer

The generic overview query matches every IFC child because the same Document summary prefix is embedded and indexed on all 303 children. This collapses RRF separation and triggers a confidence gate designed for pinpoint retrieval even though documents.summary already answers the overview. Later specific terms and pages create selective hits. Open WebUI auxiliary follow-up tasks also overwrite user_sessions conversation_summary, causing follow-up instability. Secondary issue: UUID-prefixed upload filenames create duplicate document IDs for identical IFC content.

## Source Nodes

- _scope_document_query()
- hybrid_search_and_join()
- _assess_confidence()
- persist_session_turn_activity()