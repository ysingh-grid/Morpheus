# Orchestration Guide

## Purpose

`orchestration` is the Temporal-based control layer for the document RAG
service. It coordinates existing ingestion and retrieval components without
putting database, LLM, MCP, or file-system side effects inside workflow code.

```text
Client query
  → AgentWorkflow
  → pgvector retrieval activity
  → grounded evidence
  └── no grounded evidence → wait for user signal
                                └── approved → MCP activity
  → asynchronous user-fact extraction activity
  → evidence, sources used, execution history
```

The workflow is the durable decision record. Activities are the only places
where the service may perform non-deterministic work.

## Configuration

Set these values in `.env`:

```dotenv
DATABASE_URL=postgresql://user:password@host:5432/morpheus
GEMINI_API_KEY=...
TEMPORAL_ADDRESS=localhost:7233
TAVILY_API_KEY=...
MCP_SERVER_COMMAND=npx
MCP_SERVER_ARGS=-y tavily-mcp@latest
MCP_TOOL_TIMEOUT_SECONDS=30
```

`DATABASE_URL` and `GEMINI_API_KEY` are also required by the existing
retrieval service. Run schema initialization once after deploying this version
so PostgreSQL creates `user_facts`:

```bash
uv run --env-file .env python -c "from retrieval.pg_engine import initialize_schema; initialize_schema()"
```

## Starting the worker

Start Temporal separately, then run the worker:

```bash
uv run --env-file .env python -m orchestration.worker
```

The worker connects to `TEMPORAL_ADDRESS`, listens on `rag-agent-queue`, and
registers these activities:

- `ingest_document_activity`
- `run_pgvector_retrieval_activity`
- `execute_mcp_tool_activity`
- `extract_user_facts_activity`

Use SIGINT or SIGTERM for graceful shutdown. The worker stops polling and
waits for active activity work to finish.

## Workflow contract

Start `AgentWorkflow.run(query, user_id)` on `rag-agent-queue`.

The workflow returns:

```python
{
    "status": "completed | not_found | cancelled | external_search_failed",
    "retrieval": {"status": "grounded | not_found | clarification_needed", ...},
    "evidence": [...],
    "sources_used": ["pgvector", "mcp_web_search"],
    "execution_history": [...],
}
```

`pgvector` is always listed because retrieval happens first. `mcp_web_search`
appears only after a user explicitly approves it and the MCP tool succeeds. The
response retains the original retrieval confidence decision and reasons.

`grounded` retrieval completes immediately. `not_found` returns immediately
without an external request. Only `clarification_needed` enters
`awaiting_clarification`.

## Human-in-the-loop fallback

While a workflow is paused, query its state with `get_workflow_state`. Then
signal a choice using `user_clarification_signal`:

```text
approve_web_search  → invoke Tavily MCP tool tavily_search
any other choice    → do not invoke MCP; return cancelled with no web evidence
```

The first signal is durable and final: if the worker restarts, the workflow
remains paused until a signal arrives, and later conflicting signals are
ignored.

## MCP boundary

`orchestration.mcp_client.call_mcp_tool()` creates a fresh stdio session for
one tool call. It applies `asyncio.wait_for` to both session initialization and
the tool invocation. The configured local server is Tavily MCP, which exposes
`tavily_search` with a `query` argument. Configuration is mandatory; the worker
inherits `TAVILY_API_KEY` from the environment when it launches `npx`.

MCP results are returned as JSON-compatible dictionaries and are inserted into
the workflow evidence only after the user approves the fallback. A result with
`is_error: true` becomes an activity failure, never evidence.

## User facts

After each workflow response, `extract_user_facts_activity` asks Gemini for
durable facts that the user explicitly stated. The Pydantic response permits
only `fact_key`, `fact_value`, and `category`. Each fact is upserted by
`(user_id, fact_key)` in PostgreSQL.

The activity must not infer facts from retrieved documents. It runs in the
background, so a transient fact-extraction failure must not alter the returned
grounded evidence.

## Determinism rules

Keep `workflows.py` limited to Temporal workflow APIs, deterministic state,
and serializable values. In particular, do not add:

- direct calls to PostgreSQL, Gemini, MCP, or `process_document`;
- filesystem, environment, clock, random, network, or subprocess access;
- blocking I/O or a normal `asyncio` task for external work.

Add a new activity for every side effect, register it in `worker.py`, and call
it from the workflow with a finite timeout and retry policy. Input errors that
a retry cannot repair should raise a non-retryable Temporal `ApplicationError`.

## Verification

Run the orchestration tests with real configured retrieval services:

```bash
uv run --env-file .env python -m pytest -q tests/test_orchestration.py
```

This covers a real pgvector/Gemini retrieval hit through Temporal and the local
pause → signal → MCP flow. Before deployment, also verify:

1. a grounded uploaded-document question completes without MCP;
2. an ungrounded question pauses and makes no external request before approval;
3. an approved fallback records `mcp_web_search` in `sources_used`;
4. a rejected fallback returns no web evidence;
5. `user_facts` contains only facts that were explicitly supplied by the user.
