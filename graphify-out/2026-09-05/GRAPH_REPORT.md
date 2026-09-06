# Graph Report - Morpheus-v0.1  (2026-09-05)

## Corpus Check
- 53 files · ~60,010 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 831 nodes · 1495 edges · 62 communities (55 shown, 7 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 86 edges (avg confidence: 0.88)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `1b82b6cb`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- worker.py
- Document Preprocessor Guide
- _client
- openai_api.py
- Pipe
- activities.py
- _database_url
- test_openai_api.py
- AgentWorkflow
- generate_answer_activity
- test_orchestration.py
- doc_processor.py
- build_evaluation_set.py
- TypedDict
- guardrails.py
- test_agent_graph.py
- Retrieval Guide
- evaluate.py
- _document_id
- Figure
- test_retrieval_evaluation_metrics.py
- test_guardrails.py
- process_document
- test_doc_processor.py
- export_retrieval_database
- nodes.py
- Orchestration Guide
- ingest_bundle
- _observe_terminal_state_during_persistence
- AgentState
- Agent Guide
- _fallback_plan
- _scope_document_query
- _post_chat
- pg_engine.py
- _create_agent_plan
- hybrid_search_and_join
- test_pg_engine_contract.py
- Q: Why is Morpheus not a general chatbot with optional document context and web search?
- call_mcp_tool
- verify_groundedness_node
- Q: Why does the first IFC document overview query fail while later questions improve?
- server.py
- Morpheus Open WebUI integration
- Q: What calls document_id_for_file and how does a document id flow through ingestion, PostgreSQL foreign keys, session attachments, and retrieval?
- _post_clarification
- Agent Progress
- Ingestion Progress
- Orchestration Progress
- Retrieval Progress
- BaseModel
- morpheus-v0-1
- TypedDict
- defn
- verify_borderline_confidence_activity
- schema.sql
- _run_fake_workflow
- .run
- test_imports_use_correct_docling_and_no_banned_fallbacks
- interfaces/__init__.py
- orchestration/__init__.py
- retrieval/__init__.py

## God Nodes (most connected - your core abstractions)
1. `Pipe` - 30 edges
2. `_database_url()` - 26 edges
3. `process_document()` - 23 edges
4. `_psycopg()` - 22 edges
5. `AgentState` - 21 edges
6. `compile_agent_graph()` - 19 edges
7. `_run_real_workflow()` - 18 edges
8. `AgentWorkflow` - 17 edges
9. `hybrid_search_and_join()` - 17 edges
10. `generate_answer_activity()` - 16 edges

## Surprising Connections (you probably didn't know these)
- `_run_real_workflow()` --indirect_call--> `run_agent_graph_activity()`  [INFERRED]
  tests/test_orchestration.py → orchestration/activities.py
- `_run_real_workflow()` --indirect_call--> `load_history_activity()`  [INFERRED]
  tests/test_orchestration.py → orchestration/activities.py
- `_run_real_workflow()` --indirect_call--> `persist_session_turn_activity()`  [INFERRED]
  tests/test_orchestration.py → orchestration/activities.py
- `_run_real_workflow()` --indirect_call--> `run_agent_retrieval_activity()`  [INFERRED]
  tests/test_orchestration.py → orchestration/activities.py
- `_run_real_workflow()` --indirect_call--> `verify_borderline_confidence_activity()`  [INFERRED]
  tests/test_orchestration.py → orchestration/activities.py

## Import Cycles
- None detected.

## Communities (62 total, 7 thin omitted)

### Community 0 - "worker.py"
Cohesion: 0.15
Nodes (26): ApplicationError, execute_agent_mcp_activity(), execute_mcp_tool_activity(), extract_user_facts_activity(), generate_direct_answer_activity(), ingest_document_activity(), load_history_activity(), _non_retryable() (+18 more)

### Community 1 - "Document Preprocessor Guide"
Cohesion: 0.15
Nodes (12): Acceptance checks: is a processed item useful?, Bundle-level checks, Configuration, Data model and relationships, Document Preprocessor Guide, How to use the bundle in RAG, Known limitations and operational safeguards, Native table context (+4 more)

### Community 2 - "_client"
Cohesion: 0.14
Nodes (18): AsyncClient, Response, _client(), _get_models(), _get_upload_job(), _get_workflow_status(), _post_workflow(), Create an in-process asynchronous HTTP client for the gateway. (+10 more)

### Community 3 - "openai_api.py"
Cohesion: 0.06
Nodes (57): BackgroundTasks, get, chat_completions(), ClarificationSignalRequest, DocumentUploadJobResponse, DocumentUploadResponse, get_document_upload_job(), get_workflow_status() (+49 more)

### Community 4 - "Pipe"
Cohesion: 0.05
Nodes (50): EventCall, EventEmitter, Pipe, Any, BaseModel, Path, title: Morpheus RAG Agent author: Morpheus version: 1.0.0…, Recover the original question from Open WebUI's built-in RAG wrapper. (+42 more)

### Community 5 - "activities.py"
Cohesion: 0.18
Nodes (14): ContextSufficiency, _extract_facts(), _history_for_user(), BaseModel, Temporal activities for ingestion, retrieval, MCP, and user memory., Load compact durable memories and document scope for the current session., One durable preference or entity explicitly disclosed by a user., Structured output persisted by the user-fact activity. (+6 more)

### Community 6 - "_database_url"
Cohesion: 0.12
Nodes (24): attach_documents_to_session(), _database_url(), document_ingestion_stats(), document_overview_and_join(), initialize_schema(), _psycopg(), Load stored summaries and opening parents without applying semantic rank gates., Return the PostgreSQL connection URL or fail before opening a connection. (+16 more)

### Community 7 - "test_openai_api.py"
Cohesion: 0.19
Nodes (14): Path, Async route coverage for the OpenAI-compatible gateway., A valid multipart PDF uses the existing preprocessing and pgvector loader path., The gateway exposes its one OpenAI-compatible model., Concurrent HTTP jobs must not invoke OcrMac/MPS at the same time., The upload boundary rejects non-PDF content before expensive document…, Repeated attachment delivery must reuse PostgreSQL data without rerunning…, Send one multipart upload through the ASGI application. (+6 more)

### Community 8 - "AgentWorkflow"
Cohesion: 0.13
Nodes (12): AgentWorkflow, Any, defn, Return compact references so Temporal never transports raw source payloads., Run one tool per activity so retries never replay prior side effects., Initialize durable, replay-safe workflow state., Persist only the first valid clarification decision for this workflow., Expose durable HITL and bounded-turn state to a client. (+4 more)

### Community 9 - "generate_answer_activity"
Cohesion: 0.15
Nodes (17): _compact_evidence(), _document_evidence_pages(), _document_evidence_pages_by_name(), generate_answer_activity(), _load_mcp_results(), Any, Return reference-only evidence suitable for Temporal workflow state., Retrieve from this chat's documents and return compact evidence references. (+9 more)

### Community 10 - "test_orchestration.py"
Cohesion: 0.11
Nodes (17): Resilience coverage for isolated Temporal agent tool activities., Citations show user filenames rather than Open WebUI's opaque stored name., Only visible citations with grounded filenames and full page ranges are…, An uncited model draft gets one constrained repair before it is returned., Retrieval table chunks use table_chunk_id while hydration uses the same ID…, Real retrieval and answer synthesis must keep source payloads out of workflow…, A no-answer result must avoid Gemini answer synthesis and MCP fallback., UI polling must never observe completed with an empty generated answer. (+9 more)

### Community 11 - "doc_processor.py"
Cohesion: 0.20
Nodes (14): _bounding_boxes(), _item_page_numbers(), Convert local documents into context-rich chunks for retrieval., Return page-aware bounding boxes from a Docling item., Return ordered, unique source pages from one Docling item's provenance., Create a header and row-safe textual representation from Docling table cells., Create token-bounded table chunks without splitting a table row., Extract canonical tables with native heading and caption context. (+6 more)

### Community 12 - "build_evaluation_set.py"
Cohesion: 0.11
Nodes (26): build_review_cases(), _default_document_id(), _fetch_rows(), import_human_review(), main(), _numeric_prompt(), Any, Path (+18 more)

### Community 13 - "TypedDict"
Cohesion: 0.17
Nodes (13): DocumentMetadata, ParentBlock, ProcessedChunk, ProcessedDocument, TypedDict, Coverage and integrity checks for one normalized document bundle., Normalized parent and child records produced from one source document., A retrieval child chunk linked to normalized parent content. (+5 more)

### Community 14 - "guardrails.py"
Cohesion: 0.13
Nodes (22): Groq, anonymize_pii(), GuardrailResult, _moderation_category(), _prompt_guard_blocks(), BaseModel, Local PII redaction and Groq-backed user-input guardrails., Extract Llama Guard's category code from its unsafe response. (+14 more)

### Community 15 - "test_agent_graph.py"
Cohesion: 0.17
Nodes (15): planner_node(), Let Gemini plan the turn, then select one bounded next action., Unit coverage for LangGraph ReAct tool-routing decisions., The agent retrieves only when its plan identifies relevant chat documents., The graph must compile with the requested planner and tool nodes., A bounded agent must not select another tool after its maximum turns., Direct web-search authorization must not be blocked by document retrieval…, One turn may use both session documents and web evidence before synthesis. (+7 more)

### Community 16 - "Retrieval Guide"
Cohesion: 0.17
Nodes (11): Configuration, Data relationships, Hybrid retrieval flow, Initializing the schema, Loading a preprocessed bundle, Operational constraints, Purpose, Result contract (+3 more)

### Community 17 - "evaluate.py"
Cohesion: 0.14
Nodes (22): evaluate(), EvaluationCase, _latency_summary(), _load_cases(), main(), _metric_summary(), Any, Path (+14 more)

### Community 18 - "_document_id"
Cohesion: 0.20
Nodes (13): document_content_sha256(), _document_id(), document_id_for_file(), Path, Return the complete SHA-256 digest for one document's bytes., Return a filename-independent identifier for exact-content deduplication., Retain the existing private identifier helper for compatibility., Path (+5 more)

### Community 19 - "Figure"
Cohesion: 0.23
Nodes (12): _asset_page_numbers(), Figure, _page_markdown_sections(), Return source pages recorded in a figure or table bounding-box list., Replace Docling's image placeholders with the generated figure captions., Replace canonical tables in document Markdown with stable table references., Export structured Markdown per source page before token chunking., One captioned figure and its source-document coordinates. (+4 more)

### Community 20 - "test_retrieval_evaluation_metrics.py"
Cohesion: 0.13
Nodes (18): _assess_confidence(), Assess whether the strongest RRF candidate is grounded enough to answer., Path, Unit coverage for retrieval benchmark metric calculations., Prevent an annotation-ready set from being evaluated before human sign-off., Calculate recall, MRR, and nDCG for found and missed ground-truth results., Report stable latency summaries for a small local benchmark sample., Decline a loose semantic match when it has no lexical support or close vector… (+10 more)

### Community 21 - "test_guardrails.py"
Cohesion: 0.15
Nodes (15): _groq_response(), Unit tests for the local and Groq-backed user-input guardrails., Build the minimal Groq completion shape used by the guardrails., Supported PII and secret formats are redacted locally., Prompt Guard jailbreak classifications stop the scan before Stage 3., Prompt Guard risk scores at or above the threshold block the request., GPT-OSS Safeguard JSON exposes its policy category in the result., Without Groq, local PII redaction remains active and no network client is built. (+7 more)

### Community 22 - "process_document"
Cohesion: 0.12
Nodes (19): _caption_image(), _figure_ids_in_parent(), _figure_metadata(), _ocrmac_options(), process_document(), Any, ProgressCallback, Return native Apple OCR options or raise a clear unsupported-platform error. (+11 more)

### Community 23 - "test_doc_processor.py"
Cohesion: 0.13
Nodes (17): fixture, _decode_page_chunk(), _encoding(), _page_token_stream(), Return the tokenizer used to enforce stable chunk-size boundaries., Associate every encoded Markdown token with its source page., Decode one token slice together with its ordered source-page set., Split text into bounded token groups without discarding content. (+9 more)

### Community 24 - "export_retrieval_database"
Cohesion: 0.15
Nodes (15): _database_url(), _excel_value(), export_retrieval_database(), main(), Any, Path, Export the normalized pgvector retrieval database to an Excel workbook., Run the retrieval database exporter from the command line. (+7 more)

### Community 25 - "nodes.py"
Cohesion: 0.17
Nodes (11): _conversation_retrieval_context(), _document_lookup_mode(), _document_overview_request(), _planned_action(), Any, LangGraph planning and routing nodes for the conversational agent., Extract bounded prior-turn context for an otherwise underspecified search query., Select the next unfinished tool or response action from the agent's plan. (+3 more)

### Community 26 - "Orchestration Guide"
Cohesion: 0.18
Nodes (10): Configuration, Determinism rules, Human-in-the-loop fallback, MCP boundary, Orchestration Guide, Purpose, Starting the worker, User facts (+2 more)

### Community 27 - "ingest_bundle"
Cohesion: 0.24
Nodes (11): _child_retrieval_text(), _embed(), ingest_bundle(), ProgressCallback, Serialize one embedding for PostgreSQL's vector input format., Generate 1,536-dimensional Gemini embeddings through the shared client., Remove the repeated global summary from text used for indexing and ranking., Embed and atomically load one normalized preprocessor bundle into PostgreSQL.… (+3 more)

### Community 28 - "_observe_terminal_state_during_persistence"
Cohesion: 0.17
Nodes (17): _decision_graph(), _direct_answer(), _history(), _next_action(), _observe_terminal_state_during_persistence(), _persist_session_slow(), Any, Provide compact preloaded history for deterministic workflow tests. (+9 more)

### Community 29 - "AgentState"
Cohesion: 0.12
Nodes (26): compile_agent_graph(), Any, Path, Build and render the bounded, side-effect-free LangGraph ReAct DAG., Return the planner-selected action for one Temporal activity invocation., Compile a pure ReAct decision graph with no database or network access., Render the compiled ReAct DAG and optionally write it to a PNG file., render_graph_png() (+18 more)

### Community 30 - "Agent Guide"
Cohesion: 0.22
Nodes (8): Agent Guide, Node Behavior, Operational Checks, Purpose, Run and Verify, Setup, State Contract, Temporal and HITL Flow

### Community 31 - "_fallback_plan"
Cohesion: 0.25
Nodes (8): _explicit_document_request(), _explicit_web_search_requested(), _fallback_plan(), Return a conservative tool plan if Gemini planning is temporarily unavailable., Recognize direct user authorization to search beyond uploaded documents., Recognize questions that explicitly constrain the answer to uploaded material., A document-specific request must not search unrelated globally stored documents., test_fallback_plan_requests_attachment_for_missing_document_context()

### Community 32 - "_scope_document_query"
Cohesion: 0.17
Nodes (14): Expand underspecified document follow-ups before their hybrid retrieval pass., _scope_document_query(), AgentPlan, BaseModel, Primitive, bounded state passed between LangGraph decision nodes., Structured Gemini decision for one conversational agent turn., Short follow-ups must search the prior topic rather than literal vague wording., A first-turn document question must not fabricate a prior conversational… (+6 more)

### Community 33 - "_post_chat"
Cohesion: 0.22
Nodes (9): SimpleNamespace, _post_chat(), Unsafe input must be rejected before a Temporal client is created., A completed Temporal workflow becomes a standard OpenAI chat response., A UI can receive a workflow identifier before an HITL pause can block…, Issue one chat-completions request through the ASGI application., test_chat_completion_guardrail_rejection(), test_chat_completion_success() (+1 more)

### Community 34 - "pg_engine.py"
Cohesion: 0.18
Nodes (15): consolidate_document_identity(), _file_sha256(), _jsonb(), _prioritize_policy_records(), Any, Path, Load normalized preprocessor bundles and retrieve grounded RAG evidence. This…, Wrap JSON values using psycopg's JSONB adapter. (+7 more)

### Community 35 - "_create_agent_plan"
Cohesion: 0.29
Nodes (7): _conversation_transform_request(), _create_agent_plan(), Ask Gemini to choose zero, one, or multiple tools for the current turn., Recognize follow-ups answerable entirely from a prior assistant response., parametrize, Formatting, arithmetic, and citation follow-ups reuse grounded chat output., test_follow_up_transform_uses_prior_answer_without_retrieval()

### Community 36 - "hybrid_search_and_join"
Cohesion: 0.20
Nodes (11): _flashrank_rerank(), GroundedEvidence, hybrid_search_and_join(), TypedDict, Run hybrid retrieval, optionally retaining ambiguous candidates for…, One reranked child hit with its normalized source evidence., Calibrated quality signals for the strongest RRF candidate., User-facing retrieval result with evidence only when it passes confidence… (+3 more)

### Community 37 - "test_pg_engine_contract.py"
Cohesion: 0.15
Nodes (13): _matched_table_text_for_reranking(), Return only the best table match so reranking input stays bounded., Static contract checks for the pgvector retrieval implementation., Keep the required pgvector and FTS indexes from regressing., Require RRF CTEs and relational joins in the one retrieval query., Serialize values in the format accepted by PostgreSQL's vector type., Ensure table-only hits retain one bounded, matching row for reranking., Large bundle embedding reports actual completed batches rather than elapsed… (+5 more)

### Community 38 - "Q: Why is Morpheus not a general chatbot with optional document context and web search?"
Cohesion: 0.50
Nodes (3): Answer, Q: Why is Morpheus not a general chatbot with optional document context and web search?, Source Nodes

### Community 39 - "call_mcp_tool"
Cohesion: 0.31
Nodes (8): call_mcp_tool(), Any, Async MCP stdio client used only by Temporal activities., Return the bounded MCP operation timeout., Convert an MCP tool result into JSON-compatible data., Start one stdio MCP server, invoke its tool, and return its result. Both MCP…, _result_to_dict(), _timeout_seconds()

### Community 40 - "verify_groundedness_node"
Cohesion: 0.50
Nodes (4): Apply confidence-verifier output without performing an LLM call here., verify_groundedness_node(), Non-grounded confidence must become an explicit HITL state., test_verify_groundedness_node_requests_clarification_for_weak_retrieval()

### Community 41 - "Q: Why does the first IFC document overview query fail while later questions improve?"
Cohesion: 0.50
Nodes (3): Answer, Q: Why does the first IFC document overview query fail while later questions improve?, Source Nodes

### Community 42 - "server.py"
Cohesion: 0.40
Nodes (5): main(), Uvicorn entry point for the OpenAI-compatible gateway., Start the reloadable local gateway server., Run the gateway entry point as a Python module., run_server()

### Community 43 - "Morpheus Open WebUI integration"
Cohesion: 0.40
Nodes (4): Install the Pipe, Local launch, Manual test flow, Morpheus Open WebUI integration

### Community 44 - "Q: What calls document_id_for_file and how does a document id flow through ingestion, PostgreSQL foreign keys, session attachments, and retrieval?"
Cohesion: 0.50
Nodes (3): Answer, Q: What calls document_id_for_file and how does a document id flow through ingestion, PostgreSQL foreign keys, session attachments, and retrieval?, Source Nodes

### Community 45 - "_post_clarification"
Cohesion: 0.50
Nodes (4): _post_clarification(), Approved web search reaches the workflow signal before refreshed state is…, Send one human-in-the-loop choice through the gateway., test_submit_clarification_signals_temporal_workflow()

### Community 46 - "Agent Progress"
Cohesion: 0.40
Nodes (4): Agent Progress, Completed, Known Constraints, Missing

### Community 47 - "Ingestion Progress"
Cohesion: 0.40
Nodes (4): Completed, Ingestion Progress, Known Issues, Missing

### Community 48 - "Orchestration Progress"
Cohesion: 0.40
Nodes (4): Completed, Known Constraints, Missing, Orchestration Progress

### Community 49 - "Retrieval Progress"
Cohesion: 0.40
Nodes (4): Completed, Known Constraints, Missing, Retrieval Progress

### Community 53 - "defn"
Cohesion: 0.18
Nodes (11): _answer(), _flaky_mcp(), _mcp(), defn, Keep workflow tests focused on agent orchestration behavior., Return a compact persisted-MCP reference., Fail once to prove only the MCP activity, not retrieval, is retried., Return a deterministic answer after the workflow selects its evidence. (+3 more)

### Community 54 - "verify_borderline_confidence_activity"
Cohesion: 0.20
Nodes (10): _display_document_name(), _is_borderline_confidence(), _load_evidence_by_references(), _page_grounded_child_text(), Restrict LLM verification to ambiguous retrieval near existing score gates., Use Gemini for borderline hits or mandatory document-only sufficiency checks., Hydrate only selected parent, child, table, and figure records for an answer., Remove the page-less global summary before using a child as cited evidence. (+2 more)

### Community 55 - "schema.sql"
Cohesion: 0.36
Nodes (9): agent_tool_results, children, documents, figures, parents, table_chunks, tables, user_facts (+1 more)

### Community 56 - "_run_fake_workflow"
Cohesion: 0.20
Nodes (10): _persist_session(), Keep resilience tests independent of PostgreSQL session storage., Run the workflow with isolated activity doubles and optional HITL signals., A verifier-approved borderline result should synthesize locally without Tavily., A document-plus-web plan retains compact references from both tools., The central agent can answer a normal chat turn with zero tools., _run_fake_workflow(), test_borderline_sufficient_context_bypasses_hitl() (+2 more)

### Community 57 - ".run"
Cohesion: 0.22
Nodes (7): _is_openwebui_utility_prompt(), persist_session_turn_activity(), Upsert a compact, already-sanitized summary of the latest chat turn., Identify Open WebUI metadata-generation prompts that are not user turns., Persist explicit user facts without delaying the answer response., Execute bounded decisions, isolated tools, and durable HITL resumption., run

## Knowledge Gaps
- **61 isolated node(s):** `morpheus-v0-1`, `user_facts`, `user_sessions`, `agent_tool_results`, `Purpose` (+56 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 442 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **7 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `compile_agent_graph()` connect `AgentState` to `verify_groundedness_node`, `worker.py`, `activities.py`, `test_agent_graph.py`?**
  _High betweenness centrality (0.084) - this node is a cross-community bridge._
- **Why does `process_document()` connect `process_document` to `worker.py`, `openai_api.py`, `activities.py`, `doc_processor.py`, `TypedDict`, `_document_id`, `Figure`, `test_doc_processor.py`?**
  _High betweenness centrality (0.054) - this node is a cross-community bridge._
- **Why does `_database_url()` connect `_database_url` to `worker.py`, `pg_engine.py`, `hybrid_search_and_join`, `activities.py`, `generate_answer_activity`, `test_orchestration.py`, `build_evaluation_set.py`, `evaluate.py`, `verify_borderline_confidence_activity`, `.run`, `ingest_bundle`?**
  _High betweenness centrality (0.039) - this node is a cross-community bridge._
- **Are the 16 inferred relationships involving `AgentState` (e.g. with `compile_agent_graph()` and `_route_from_planner()`) actually correct?**
  _`AgentState` has 16 INFERRED edges - model-reasoned connections that need verification._
- **What connects `morpheus-v0-1`, `user_facts`, `user_sessions` to the rest of the system?**
  _61 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `worker.py` be split into smaller, more focused modules?**
  _Cohesion score 0.1455026455026455 - nodes in this community are weakly interconnected._
- **Should `_client` be split into smaller, more focused modules?**
  _Cohesion score 0.1437908496732026 - nodes in this community are weakly interconnected._