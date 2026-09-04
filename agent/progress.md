# Agent Progress

## Completed

- Added `AgentState` for one graph turn: query identity, messages, retrieved
  evidence, MCP results, HITL state, and final answer.
- Added `load_history_activity` for durable `user_facts` and `user_sessions`,
  while `load_history_node` injects that already-loaded history into graph state.
- Added planner routing for pgvector hybrid retrieval, Tavily MCP fallback,
  clarification, and answer generation.
- Split history loading, retrieval, borderline verification, Tavily, and answer
  generation into separate Temporal activities. Retries no longer replay prior
  external operations.
- Added reference-only workflow state. Parent/table/figure payloads and raw
  Tavily results remain in PostgreSQL until answer generation hydrates them.
- Added `agent_tool_results` to persist raw MCP results outside Temporal payloads.
- Added a five-turn workflow cap and LangGraph recursion limit.
- Added a structured Gemini context-sufficiency check for borderline retrieval
  confidence before requesting HITL.
- Added grounded answer generation through `generate_answer_activity`, which
  hydrates only the selected evidence and tool-result references.
- Added `run_agent_graph_activity` as a bounded, side-effect-free decision pass;
  `AgentWorkflow` owns durable HITL state and invokes individual tool activities.
- Added `user_sessions` and its user lookup index to the pgvector schema.
- Added `compile_agent_graph()` and `render_graph_png()`.
- Added `langgraph` to the project dependencies.
- Verified a real pgvector and Gemini graph execution, and the full test suite
  (`23 passed`).
- Verified a real Tavily result through `execute_agent_mcp_activity`; the raw
  7,967-byte payload was stored in PostgreSQL while workflow-facing state kept
  only its tool-result reference.
- Refreshed Graphify after implementation (`665` nodes and `6,571` edges).

## Missing

- Persist or summarize conversation turns into `user_sessions`; the current
  graph reads session summaries but no activity writes them yet.
- Calibrate the borderline-confidence range against the human-verified
  evaluation set before changing its score boundaries.
- Add API/UI support to display the clarification state and send the durable
  approval or cancellation signal.
- Add citation formatting and answer-quality evaluation for `final_answer`.
- Add production observability for graph decisions, node durations, and tool
  failure reasons.

## Known Constraints

- Graph nodes are pure decision code. Database, Gemini, and MCP work belongs in
  individual Temporal activities and must not execute in `workflows.py`.
- The graph only invokes Tavily after Temporal receives
  `approve_web_search`; cancellation produces no MCP result.
- The existing worker must be restarted after deploying this component so it
  registers `run_agent_graph_activity` and `generate_answer_activity`.
- `render_graph_png()` may require Mermaid rendering access in the local
  environment; it does not participate in workflow execution.
