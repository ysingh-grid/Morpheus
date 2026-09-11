# Graph Report - Morpheus-v0.1  (2026-09-06)

## Corpus Check
- 57 files · ~60,780 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 851 nodes · 1516 edges · 67 communities (57 shown, 10 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 86 edges (avg confidence: 0.88)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `b1821f3e`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- activities.py
- Document Preprocessor Guide
- test_openai_api.py
- openai_api.py
- Pipe
- _extract_facts
- _database_url
- _upload_pdf
- AgentWorkflow
- _compact_evidence
- test_agent_workflow_generates_real_answer_from_compact_references
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
- WorkflowStateResponse
- process_document
- test_doc_processor.py
- export_retrieval_database
- nodes.py
- Orchestration Guide
- DocumentUploadJobResponse
- test_orchestration.py
- AgentState
- Agent Guide
- _fallback_plan
- _scope_document_query
- document_overview_and_join
- pg_engine.py
- _create_agent_plan
- _process_saved_documents
- ingest_bundle
- Q: Why is Morpheus not a general chatbot with optional document context and web search?
- call_mcp_tool
- verify_groundedness_node
- Q: Why does the first IFC document overview query fail while later questions improve?
- server.py
- Morpheus Open WebUI integration
- Q: What calls document_id_for_file and how does a document id flow through ingestion, PostgreSQL foreign keys, session attachments, and retrieval?
- Q: What is Morpheus still missing relative to agentic RAG over personal documents?
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
- _workflow_id
- test_imports_use_correct_docling_and_no_banned_fallbacks
- test_document_evidence_pages_collects_text_table_and_figure_provenance
- interfaces/__init__.py
- orchestration/__init__.py
- retrieval/__init__.py
- test_agent_workflow_returns_real_not_found_without_human_pause

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
- `_observe_terminal_state_during_persistence()` --uses--> `AgentWorkflow`  [INFERRED]
  tests/test_orchestration.py → orchestration/workflows.py
- `_run_fake_workflow()` --uses--> `AgentWorkflow`  [INFERRED]
  tests/test_orchestration.py → orchestration/workflows.py
- `_run_real_workflow()` --uses--> `AgentWorkflow`  [INFERRED]
  tests/test_orchestration.py → orchestration/workflows.py
- `run_agent_graph_activity()` --calls--> `compile_agent_graph()`  [EXTRACTED]
  orchestration/activities.py → agent/graph.py
- `test_compile_agent_graph_exposes_the_react_dag()` --calls--> `compile_agent_graph()`  [EXTRACTED]
  tests/test_agent_graph.py → agent/graph.py

## Import Cycles
- None detected.

## Communities (67 total, 10 thin omitted)

### Community 0 - "activities.py"
Cohesion: 0.11
Nodes (47): _document_evidence_pages(), _document_evidence_pages_by_name(), execute_agent_mcp_activity(), execute_mcp_tool_activity(), extract_user_facts_activity(), generate_answer_activity(), generate_direct_answer_activity(), ingest_document_activity() (+39 more)

### Community 1 - "Document Preprocessor Guide"
Cohesion: 0.15
Nodes (12): Acceptance checks: is a processed item useful?, Bundle-level checks, Configuration, Data model and relationships, Document Preprocessor Guide, How to use the bundle in RAG, Known limitations and operational safeguards, Native table context (+4 more)

### Community 2 - "test_openai_api.py"
Cohesion: 0.11
Nodes (29): AsyncClient, Response, _client(), _get_models(), _get_upload_job(), _get_workflow_status(), _post_chat(), _post_clarification() (+21 more)

### Community 3 - "openai_api.py"
Cohesion: 0.18
Nodes (17): chat_completions(), _message_content(), Any, OpenAI-compatible HTTP gateway for the durable RAG agent workflow., Screen only the current turn and locally redact conversation history., Apply one thread-safe, monotonic update to an in-process upload job., Start one durable agent workflow and return its handle and stable identifier., Screen a chat turn and await its Temporal agent workflow response. (+9 more)

### Community 4 - "Pipe"
Cohesion: 0.05
Nodes (50): EventCall, EventEmitter, Pipe, Any, BaseModel, Path, title: Morpheus RAG Agent author: Morpheus version: 1.0.0…, Recover the original question from Open WebUI's built-in RAG wrapper. (+42 more)

### Community 5 - "_extract_facts"
Cohesion: 0.18
Nodes (11): ContextSufficiency, _extract_facts(), BaseModel, One durable preference or entity explicitly disclosed by a user., Structured output persisted by the user-fact activity., Structured borderline-confidence assessment for retrieved context., Ask Gemini for only user facts explicitly stated in the exchange., Compact conversational memory and uploaded-document scope for one chat. (+3 more)

### Community 6 - "_database_url"
Cohesion: 0.11
Nodes (26): _history_for_user(), _load_mcp_results(), Load compact durable memories and document scope for the current session., Hydrate stored tool payloads only while generating the answer., attach_documents_to_session(), _database_url(), document_ingestion_stats(), hybrid_search_and_join() (+18 more)

### Community 7 - "_upload_pdf"
Cohesion: 0.22
Nodes (11): Path, A valid multipart PDF uses the existing preprocessing and pgvector loader path., Concurrent HTTP jobs must not invoke OcrMac/MPS at the same time., The upload boundary rejects non-PDF content before expensive document…, Repeated attachment delivery must reuse PostgreSQL data without rerunning…, Send one multipart upload through the ASGI application., test_upload_jobs_serialize_document_processor_access(), test_upload_pdf_processes_and_loads_normalized_bundle() (+3 more)

### Community 8 - "AgentWorkflow"
Cohesion: 0.12
Nodes (15): AgentWorkflow, Any, defn, Persist explicit user facts without delaying the answer response., Return compact references so Temporal never transports raw source payloads., Run one tool per activity so retries never replay prior side effects., Initialize durable, replay-safe workflow state., Persist only the first valid clarification decision for this workflow. (+7 more)

### Community 9 - "_compact_evidence"
Cohesion: 0.50
Nodes (4): _compact_evidence(), Return reference-only evidence suitable for Temporal workflow state., Retrieval table chunks use table_chunk_id while hydration uses the same ID…, test_compact_evidence_accepts_retrieval_table_chunk_identifier()

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
Cohesion: 0.06
Nodes (44): Groq, anonymize_pii(), GuardrailResult, _moderation_category(), _prompt_guard_blocks(), BaseModel, Local PII redaction and Groq-backed user-input guardrails., Extract Llama Guard's category code from its unsafe response. (+36 more)

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
Cohesion: 0.12
Nodes (20): _assess_confidence(), Assess whether the strongest RRF candidate is grounded enough to answer., Path, Unit coverage for retrieval benchmark metric calculations., A strongly matched table row is not rejected because adjacent rows rank closely., Prevent an annotation-ready set from being evaluated before human sign-off., Calculate recall, MRR, and nDCG for found and missed ground-truth results., Report stable latency summaries for a small local benchmark sample. (+12 more)

### Community 21 - "WorkflowStateResponse"
Cohesion: 0.16
Nodes (15): ClarificationSignalRequest, DocumentUploadResponse, get_workflow_status(), BaseModel, Query the durable workflow state needed for UI progress and HITL prompts., Validate a human decision before it reaches a Temporal workflow., Expose the compact, durable state required by a polling UI., Describe one completed PDF ingestion performed through the HTTP gateway. (+7 more)

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

### Community 27 - "DocumentUploadJobResponse"
Cohesion: 0.25
Nodes (9): get, DocumentUploadJobResponse, get_document_upload_job(), list_models(), Return a validated copy of one upload job or a stable 404 response., Return the latest completed-work percentage for one PDF upload job., Return the single OpenAI-compatible model exposed by this service., Expose background PDF ingestion progress to polling user interfaces. (+1 more)

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

### Community 33 - "document_overview_and_join"
Cohesion: 0.22
Nodes (9): document_overview_and_join(), GroundedEvidence, TypedDict, Load stored summaries and opening parents without applying semantic rank gates., One reranked child hit with its normalized source evidence., Calibrated quality signals for the strongest RRF candidate., User-facing retrieval result with evidence only when it passes confidence…, RetrievalConfidence (+1 more)

### Community 34 - "pg_engine.py"
Cohesion: 0.13
Nodes (21): consolidate_document_identity(), _file_sha256(), _flashrank_rerank(), _jsonb(), _matched_table_text_for_reranking(), _prioritize_policy_records(), Any, Path (+13 more)

### Community 35 - "_create_agent_plan"
Cohesion: 0.29
Nodes (7): _conversation_transform_request(), _create_agent_plan(), Ask Gemini to choose zero, one, or multiple tools for the current turn., Recognize follow-ups answerable entirely from a prior assistant response., parametrize, Formatting, arithmetic, and citation follow-ups reuse grounded chat output., test_follow_up_transform_uses_prior_answer_without_retrieval()

### Community 36 - "_process_saved_documents"
Cohesion: 0.20
Nodes (14): BackgroundTasks, _process_saved_documents(), Path, Validate one PDF upload and persist it under an opaque local filename., Preprocess, store, and attach saved PDFs while reporting completed work., Execute a background upload job and retain its latest pollable state., Upload one or more PDFs, preprocess them, and atomically load pgvector tiers., Persist PDFs quickly and process them in a pollable background job. (+6 more)

### Community 37 - "ingest_bundle"
Cohesion: 0.12
Nodes (20): _child_retrieval_text(), _embed(), ingest_bundle(), ProgressCallback, Serialize one embedding for PostgreSQL's vector input format., Generate 1,536-dimensional Gemini embeddings through the shared client., Remove the repeated global summary from text used for indexing and ranking., Embed and atomically load one normalized preprocessor bundle into PostgreSQL.… (+12 more)

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

### Community 45 - "Q: What is Morpheus still missing relative to agentic RAG over personal documents?"
Cohesion: 0.50
Nodes (3): Answer, Q: What is Morpheus still missing relative to agentic RAG over personal documents?, Source Nodes

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

### Community 60 - "_workflow_id"
Cohesion: 0.50
Nodes (4): Create one unique workflow identity while retaining the chat scope in its name., _workflow_id(), A repeated submission in one chat must not collide with an active Temporal run., test_workflow_id_is_unique_for_each_chat_turn()

## Knowledge Gaps
- **69 isolated node(s):** `morpheus-v0-1`, `user_facts`, `user_sessions`, `agent_tool_results`, `Purpose` (+64 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 456 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **10 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `compile_agent_graph()` connect `AgentState` to `verify_groundedness_node`, `activities.py`, `test_agent_graph.py`?**
  _High betweenness centrality (0.081) - this node is a cross-community bridge._
- **Why does `process_document()` connect `process_document` to `activities.py`, `openai_api.py`, `_process_saved_documents`, `doc_processor.py`, `TypedDict`, `_document_id`, `Figure`, `test_doc_processor.py`?**
  _High betweenness centrality (0.052) - this node is a cross-community bridge._
- **Why does `_database_url()` connect `_database_url` to `activities.py`, `document_overview_and_join`, `pg_engine.py`, `ingest_bundle`, `build_evaluation_set.py`, `evaluate.py`, `test_orchestration.py`?**
  _High betweenness centrality (0.038) - this node is a cross-community bridge._
- **Are the 16 inferred relationships involving `AgentState` (e.g. with `compile_agent_graph()` and `_route_from_planner()`) actually correct?**
  _`AgentState` has 16 INFERRED edges - model-reasoned connections that need verification._
- **What connects `morpheus-v0-1`, `user_facts`, `user_sessions` to the rest of the system?**
  _69 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `activities.py` be split into smaller, more focused modules?**
  _Cohesion score 0.10530612244897959 - nodes in this community are weakly interconnected._
- **Should `test_openai_api.py` be split into smaller, more focused modules?**
  _Cohesion score 0.1103448275862069 - nodes in this community are weakly interconnected._