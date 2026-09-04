# Agent Guide

## Purpose

`agent` is the cognitive layer for the RAG service. It uses LangGraph to choose
the next action, while Temporal owns durable execution and human approval.

```text
Temporal workflow
  -> load history activity
  -> bounded LangGraph decision activity
  -> one selected tool activity (retrieve, verify, Tavily, or answer)
  -> bounded LangGraph decision activity
  \-> clarification -> Temporal signal -> Tavily -> answer
```

The graph runs inside `run_agent_graph_activity` and is side-effect free. It
must never call PostgreSQL, Gemini, or MCP directly; the workflow invokes those
operations as isolated Temporal activities.

## Setup

The existing environment needs PostgreSQL, Gemini, Temporal, and Tavily:

```dotenv
DATABASE_URL=postgresql://user:password@host:5432/morpheus
GEMINI_API_KEY=...
TEMPORAL_ADDRESS=localhost:7233
TAVILY_API_KEY=...
MCP_SERVER_COMMAND=npx
MCP_SERVER_ARGS="-y tavily-mcp@latest"
MCP_TOOL_TIMEOUT_SECONDS=30
```

Apply the schema once to create `user_sessions` and `agent_tool_results`:

```bash
uv run --env-file .env python -c "from retrieval.pg_engine import initialize_schema; initialize_schema()"
```

Restart the worker after the Phase 4 deployment:

```bash
uv run --env-file .env python -m orchestration.worker
```

## State Contract

`AgentState` carries the original user inputs and all decisions made during one
turn. The required fields are:

| Field | Purpose |
| --- | --- |
| `query`, `user_id`, `session_id` | Identify the user request and session. |
| `messages`, `history` | Current messages plus PostgreSQL-backed history. |
| `retrieved_evidence` | Compact pgvector references (`chunk_id`, `parent_id`, scores). |
| `mcp_results` | Stored Tavily-result references, never raw payloads. |
| `clarification_needed`, `user_choice` | HITL state shared with Temporal. |
| `final_answer` | Gemini answer constrained to selected evidence. |

The state also stores `retrieval_response`, `next_action`,
`iteration_count`, and `max_turns` for internal routing. It has a five-turn
limit; on exhaustion it returns a safe clarification response.

## Node Behavior

1. `load_history_activity` loads `user_facts` and the current `user_sessions`
   summary; `load_history_node` injects it into state.
2. `planner_node` chooses `hybrid_search`, `mcp_search`,
   `ask_clarification`, or `generate_answer`.
3. `hybrid_search_node`, `mcp_search_node`, and `synthesize_answer_node` emit
   a tool choice; Temporal executes it in a dedicated activity.
4. `verify_groundedness_node` applies the structured borderline verifier and
   routes insufficient evidence to HITL. It preserves `not_found` as an
   immediate no-answer outcome.
5. `execute_agent_mcp_activity` calls Tavily only after `user_choice` is
   `approve_web_search` and stores the raw payload in PostgreSQL.
6. `generate_answer_activity` hydrates selected references only while creating
   the final answer.

## Temporal and HITL Flow

`AgentWorkflow` alternates a bounded graph decision pass with exactly one
side-effecting activity. If the graph sets `clarification_needed`, the workflow
pauses durably. The client can
inspect `get_workflow_state` and then send `user_clarification_signal`.

```text
approve_web_search -> graph reruns -> Tavily -> final answer
any other choice  -> graph reruns -> cancelled response, no Tavily result
```

The first signal is final. Later signals are recorded as ignored and cannot
reverse the user decision.

## Run and Verify

Run the focused tests:

```bash
uv run --env-file .env python -m pytest -q tests/test_agent_graph.py tests/test_orchestration.py
```

Run the complete suite:

```bash
uv run --env-file .env python -m pytest -x --tb=short
```

Render the DAG when visual inspection is useful:

```bash
uv run --env-file .env python -c "from agent.graph import render_graph_png; render_graph_png('agent/graph.png')"
```

## Operational Checks

A useful graph result has all of the following:

- `retrieval.status == "grounded"` and non-empty compact `retrieved_evidence` for an
  uploaded-document answer;
- a non-empty `final_answer` produced from that evidence;
- `mcp_results == []` unless the user explicitly approved web search;
- `sources_used` includes `mcp_web_search` only after a successful Tavily call;
- `not_found` returns no unsupported evidence and never invokes Tavily.

For ambiguous queries, confirm the workflow status becomes
`awaiting_clarification` before any MCP tool starts. This is the key guardrail
that keeps external search user-controlled.
