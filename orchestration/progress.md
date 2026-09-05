# Orchestration Progress

## Completed

- Added the `orchestration` package as the Temporal boundary for the RAG agent.
- Added `AgentWorkflow`, which keeps workflow execution deterministic and moves database, network, Gemini, ingestion, and MCP work into Temporal activities.
- Added `ingest_document_activity` to process a local document and atomically load its normalized bundle into PostgreSQL.
- Added `run_pgvector_retrieval_activity` to retain the Phase 2 confidence decision and evidence through the workflow.
- Added a human-in-the-loop pause only for `clarification_needed`; `not_found` completes without an unnecessary external fallback.
- Added user-approved MCP web-search fallback. The workflow never invokes MCP until the signal choice is `approve_web_search`.
- Added an async MCP stdio client with bounded initialization and tool-call timeouts.
- Added structured Gemini user-fact extraction using Pydantic, with PostgreSQL upserts into `user_facts`.
- Added `user_facts` and its lookup index to the unified pgvector schema.
- Added the `rag-agent-queue` Temporal worker with a bounded activity thread pool and SIGINT/SIGTERM shutdown handling.
- Added local Temporal integration coverage for real pgvector retrieval and for the pause → approval signal → MCP branch.
- Made the first valid HITL decision final, preventing a later conflicting signal from reversing it.
- Required explicit MCP server configuration and reject MCP error payloads instead of returning them as evidence.
- Verified real Gemini structured output persisted a fact, then removed the isolated smoke-test record.
- Verified the configured Tavily MCP server through the Temporal approval path. A real
  `tavily_search` call returned non-error evidence after `approve_web_search`.
- Verified the locally running Temporal server and `rag-agent-queue` worker with a
  real pgvector and Gemini grounded-retrieval workflow.
- Refreshed Graphify after the component was added.
- Added page-aware answer synthesis with HTML superscript citations, grounded-page validation, and one constrained repair attempt for uncited drafts.

## Missing

- Add an API or UI caller that starts workflows, displays `awaiting_clarification`,
  and sends the approval or cancellation signal.
- Add production connection pooling, migrations, authentication/tenant scoping, and observability around the PostgreSQL and Temporal clients.
- Calibrate the retrieval confidence threshold on a human-verified evaluation set before enabling automatic web-search suggestions in production.

## Known Constraints

- A Temporal workflow must remain deterministic. Do not add direct database access, Gemini calls, MCP calls, file access, clocks, randomness, or environment reads to `workflows.py`.
- A `clarification_needed` workflow still waits indefinitely for a user signal; a signal-expiry policy has not been added.
- User-fact extraction is deliberately fire-and-forget with `ABANDON` cancellation. A successful evidence response is not delayed by this non-critical persistence task.
- MCP fallback uses Tavily's `tavily_search` tool with `{"query": "..."}`. The worker process must inherit `TAVILY_API_KEY` from `.env`.
- The document-ingestion activity can be long-running. Its Temporal `start_to_close_timeout` must be increased from the workflow caller if the document exceeds the configured activity window.
