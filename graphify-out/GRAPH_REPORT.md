# Graph Report - Morpheus-v0.1  (2026-09-05)

## Corpus Check
- 56 files · ~60,477 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 845 nodes · 1507 edges · 66 communities (57 shown, 9 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 86 edges (avg confidence: 0.88)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `1b82b6cb`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- activities.py
- Document Preprocessor Guide
- _client
- openai_api.py
- Pipe
- _extract_facts
- _database_url
- test_openai_api.py
- AgentWorkflow
- _compact_evidence
- _run_real_workflow
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
- _psycopg
- test_orchestration.py
- AgentState
- Agent Guide
- _fallback_plan
- _scope_document_query
- _post_chat
- pg_engine.py
- _create_agent_plan
- _process_saved_documents
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
- Q: Why was a benign sinusitis document question blocked as confidential-data disclosure?
- _display_document_name
- schema.sql
- Q: What is the current confidence layer in Morpheus?
- Q: Are the current retrieval confidence thresholds too strict and should they be reduced?
- _page_grounded_child_text
- _source_citations_are_valid
- test_generate_answer_repairs_missing_page_citation
- test_imports_use_correct_docling_and_no_banned_fallbacks
- test_document_evidence_pages_collects_text_table_and_figure_provenance
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

## Communities (66 total, 9 thin omitted)

### Community 0 - "activities.py"
Cohesion: 0.10
Nodes (47): _document_evidence_pages(), _document_evidence_pages_by_name(), execute_agent_mcp_activity(), execute_mcp_tool_activity(), extract_user_facts_activity(), generate_answer_activity(), generate_direct_answer_activity(), ingest_document_activity() (+39 more)

### Community 1 - "Document Preprocessor Guide"
Cohesion: 0.15
Nodes (12): Acceptance checks: is a processed item useful?, Bundle-level checks, Configuration, Data model and relationships, Document Preprocessor Guide, How to use the bundle in RAG, Known limitations and operational safeguards, Native table context (+4 more)

### Community 2 - "_client"
Cohesion: 0.14
Nodes (18): AsyncClient, Response, _client(), _get_models(), _get_upload_job(), _get_workflow_status(), _post_workflow(), Create an in-process asynchronous HTTP client for the gateway. (+10 more)

### Community 3 - "openai_api.py"
Cohesion: 0.07
Nodes (49): BackgroundTasks, get, chat_completions(), ClarificationSignalRequest, DocumentUploadJobResponse, DocumentUploadResponse, get_document_upload_job(), get_workflow_status() (+41 more)

### Community 4 - "Pipe"
Cohesion: 0.05
Nodes (50): EventCall, EventEmitter, Pipe, Any, BaseModel, Path, title: Morpheus RAG Agent author: Morpheus version: 1.0.0…, Recover the original question from Open WebUI's built-in RAG wrapper. (+42 more)

### Community 5 - "_extract_facts"
Cohesion: 0.18
Nodes (11): ContextSufficiency, _extract_facts(), BaseModel, One durable preference or entity explicitly disclosed by a user., Structured output persisted by the user-fact activity., Structured borderline-confidence assessment for retrieved context., Ask Gemini for only user facts explicitly stated in the exchange., Compact conversational memory and uploaded-document scope for one chat. (+3 more)

### Community 6 - "_database_url"
Cohesion: 0.18
Nodes (16): _database_url(), hybrid_search_and_join(), initialize_schema(), Run hybrid retrieval, optionally retaining ambiguous candidates for…, Return the PostgreSQL connection URL or fail before opening a connection., Create the pgvector extension, relational tables, and retrieval indexes., _assert_persisted_two_tier_records(), _bundle() (+8 more)

### Community 7 - "test_openai_api.py"
Cohesion: 0.19
Nodes (14): Path, Async route coverage for the OpenAI-compatible gateway., A valid multipart PDF uses the existing preprocessing and pgvector loader path., The gateway exposes its one OpenAI-compatible model., Concurrent HTTP jobs must not invoke OcrMac/MPS at the same time., The upload boundary rejects non-PDF content before expensive document…, Repeated attachment delivery must reuse PostgreSQL data without rerunning…, Send one multipart upload through the ASGI application. (+6 more)

### Community 8 - "AgentWorkflow"
Cohesion: 0.12
Nodes (15): AgentWorkflow, Any, defn, Persist explicit user facts without delaying the answer response., Return compact references so Temporal never transports raw source payloads., Run one tool per activity so retries never replay prior side effects., Initialize durable, replay-safe workflow state., Persist only the first valid clarification decision for this workflow. (+7 more)

### Community 9 - "_compact_evidence"
Cohesion: 0.50
Nodes (4): _compact_evidence(), Return reference-only evidence suitable for Temporal workflow state., Retrieval table chunks use table_chunk_id while hydration uses the same ID…, test_compact_evidence_accepts_retrieval_table_chunk_identifier()

### Community 10 - "_run_real_workflow"
Cohesion: 0.33
Nodes (6): Run actual retrieval and Gemini answer synthesis through Temporal., Real retrieval and answer synthesis must keep source payloads out of workflow…, A no-answer result must avoid Gemini answer synthesis and MCP fallback., _run_real_workflow(), test_agent_workflow_generates_real_answer_from_compact_references(), test_agent_workflow_returns_real_not_found_without_human_pause()

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
Cohesion: 0.15
Nodes (20): evaluate(), EvaluationCase, _load_cases(), main(), Any, Path, TypedDict, _rank() (+12 more)

### Community 18 - "_document_id"
Cohesion: 0.20
Nodes (13): document_content_sha256(), _document_id(), document_id_for_file(), Path, Return the complete SHA-256 digest for one document's bytes., Return a filename-independent identifier for exact-content deduplication., Retain the existing private identifier helper for compatibility., Path (+5 more)

### Community 19 - "Figure"
Cohesion: 0.23
Nodes (12): _asset_page_numbers(), Figure, _page_markdown_sections(), Return source pages recorded in a figure or table bounding-box list., Replace Docling's image placeholders with the generated figure captions., Replace canonical tables in document Markdown with stable table references., Export structured Markdown per source page before token chunking., One captioned figure and its source-document coordinates. (+4 more)

### Community 20 - "test_retrieval_evaluation_metrics.py"
Cohesion: 0.10
Nodes (24): _latency_summary(), _metric_summary(), Calculate retrieval metrics for cases with a single known relevant result., Summarize per-query latency samples in milliseconds., _assess_confidence(), Assess whether the strongest RRF candidate is grounded enough to answer., Path, Unit coverage for retrieval benchmark metric calculations. (+16 more)

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

### Community 27 - "_psycopg"
Cohesion: 0.19
Nodes (13): _history_for_user(), Load compact durable memories and document scope for the current session., _child_retrieval_text(), _embed(), ingest_bundle(), _psycopg(), ProgressCallback, Load psycopg only when PostgreSQL access is requested. (+5 more)

### Community 28 - "test_orchestration.py"
Cohesion: 0.10
Nodes (42): ApplicationError, _answer(), _decision_graph(), _direct_answer(), _flaky_mcp(), _history(), _mcp(), _next_action() (+34 more)

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
Cohesion: 0.11
Nodes (24): consolidate_document_identity(), document_overview_and_join(), _file_sha256(), GroundedEvidence, _jsonb(), _prioritize_policy_records(), Any, Path (+16 more)

### Community 35 - "_create_agent_plan"
Cohesion: 0.29
Nodes (7): _conversation_transform_request(), _create_agent_plan(), Ask Gemini to choose zero, one, or multiple tools for the current turn., Recognize follow-ups answerable entirely from a prior assistant response., parametrize, Formatting, arithmetic, and citation follow-ups reuse grounded chat output., test_follow_up_transform_uses_prior_answer_without_retrieval()

### Community 36 - "_process_saved_documents"
Cohesion: 0.18
Nodes (12): _process_saved_documents(), Path, Preprocess, store, and attach saved PDFs while reporting completed work., Execute a background upload job and retain its latest pollable state., Describe one completed PDF ingestion performed through the HTTP gateway., _run_upload_job(), UploadedDocumentResult, attach_documents_to_session() (+4 more)

### Community 37 - "test_pg_engine_contract.py"
Cohesion: 0.13
Nodes (15): _flashrank_rerank(), _matched_table_text_for_reranking(), Return only the best table match so reranking input stays bounded., Rerank parent evidence with FlashRank after the SQL retrieval pass., Static contract checks for the pgvector retrieval implementation., Keep the required pgvector and FTS indexes from regressing., Require RRF CTEs and relational joins in the one retrieval query., Serialize values in the format accepted by PostgreSQL's vector type. (+7 more)

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

### Community 53 - "Q: Why was a benign sinusitis document question blocked as confidential-data disclosure?"
Cohesion: 0.50
Nodes (3): Answer, Q: Why was a benign sinusitis document question blocked as confidential-data disclosure?, Source Nodes

### Community 54 - "_display_document_name"
Cohesion: 0.50
Nodes (4): _display_document_name(), Hide Open WebUI's opaque upload prefix from human-facing citations., Citations show user filenames rather than Open WebUI's opaque stored name., test_display_document_name_removes_only_openwebui_upload_prefix()

### Community 55 - "schema.sql"
Cohesion: 0.36
Nodes (9): agent_tool_results, children, documents, figures, parents, table_chunks, tables, user_facts (+1 more)

### Community 56 - "Q: What is the current confidence layer in Morpheus?"
Cohesion: 0.50
Nodes (3): Answer, Q: What is the current confidence layer in Morpheus?, Source Nodes

### Community 57 - "Q: Are the current retrieval confidence thresholds too strict and should they be reduced?"
Cohesion: 0.50
Nodes (3): Answer, Q: Are the current retrieval confidence thresholds too strict and should they be reduced?, Source Nodes

### Community 58 - "_page_grounded_child_text"
Cohesion: 0.50
Nodes (4): _page_grounded_child_text(), Remove the page-less global summary before using a child as cited evidence., Generated document summaries must not masquerade as page-local evidence., test_page_grounded_child_text_removes_global_summary()

### Community 59 - "_source_citations_are_valid"
Cohesion: 0.50
Nodes (4): Require visible source citations and reject unavailable document-page…, _source_citations_are_valid(), Only visible citations with grounded filenames and full page ranges are…, test_source_citation_validation_rejects_missing_or_unavailable_pages()

## Knowledge Gaps
- **67 isolated node(s):** `morpheus-v0-1`, `user_facts`, `user_sessions`, `agent_tool_results`, `Purpose` (+62 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 452 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **9 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `compile_agent_graph()` connect `AgentState` to `verify_groundedness_node`, `activities.py`, `test_agent_graph.py`?**
  _High betweenness centrality (0.082) - this node is a cross-community bridge._
- **Why does `process_document()` connect `process_document` to `activities.py`, `openai_api.py`, `_process_saved_documents`, `doc_processor.py`, `TypedDict`, `_document_id`, `Figure`, `test_doc_processor.py`?**
  _High betweenness centrality (0.052) - this node is a cross-community bridge._
- **Why does `_database_url()` connect `_database_url` to `activities.py`, `pg_engine.py`, `_process_saved_documents`, `_run_real_workflow`, `build_evaluation_set.py`, `evaluate.py`, `_psycopg`, `test_orchestration.py`?**
  _High betweenness centrality (0.038) - this node is a cross-community bridge._
- **Are the 16 inferred relationships involving `AgentState` (e.g. with `compile_agent_graph()` and `_route_from_planner()`) actually correct?**
  _`AgentState` has 16 INFERRED edges - model-reasoned connections that need verification._
- **What connects `morpheus-v0-1`, `user_facts`, `user_sessions` to the rest of the system?**
  _67 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `activities.py` be split into smaller, more focused modules?**
  _Cohesion score 0.10204081632653061 - nodes in this community are weakly interconnected._
- **Should `_client` be split into smaller, more focused modules?**
  _Cohesion score 0.1437908496732026 - nodes in this community are weakly interconnected._