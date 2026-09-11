# Graph Report - Morpheus-v0.1  (2026-09-08)

## Corpus Check
- 71 files · ~75,629 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1254 nodes · 2405 edges · 92 communities (84 shown, 8 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 152 edges (avg confidence: 0.87)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `5903aec6`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- activities.py
- Document Preprocessor Guide
- test_agent_graph.py
- scan_user_input
- test_openwebui_pipe.py
- _client
- test_guardrails.py
- test_openai_api.py
- AgentWorkflow
- _post_chat
- document_id_for_file
- state.py
- build_evaluation_set.py
- nodes.py
- doc_processor.py
- pg_engine.py
- Retrieval Guide
- evaluate.py
- openai_api.py
- _page_markdown_sections
- _sanitize_messages
- _load_evidence_by_references
- WorkflowStateResponse
- test_doc_processor.py
- export_retrieval_database
- get
- Orchestration Guide
- start_document_upload_job
- test_orchestration.py
- AgentState
- Agent Guide
- process_document
- _scope_document_query
- Any
- TypedDict
- test_pg_engine_contract.py
- Pipe
- .pipe
- Q: Why is Morpheus not a general chatbot with optional document context and web search?
- mcp_client.py
- Any
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
- _conversation_retrieval_context
- schema.sql
- Q: What is the current confidence layer in Morpheus?
- Q: Are the current retrieval confidence thresholds too strict and should they be reduced?
- Q: How does clarification approval resume a Temporal agent workflow?
- _history_for_user
- Q: How was historical chat content prevented from causing guardrail denials?
- test_imports_use_correct_docling_and_no_banned_fallbacks
- .get_reindex_status
- interfaces/__init__.py
- orchestration/__init__.py
- retrieval/__init__.py
- _run_fake_workflow
- Q: How are role validation and guardrail screening enforced across chat messages?
- _process_saved_documents
- _resolve_document_name
- ._format_source_bubbles
- _run_batch_reindex_workflow
- Q: How does durable PDF ingestion flow from the FastAPI gateway through Temporal to PostgreSQL?
- DocumentIngestionWorkflow
- _get_upload_job
- Q: How does the ingestion workflow avoid Temporal payload limits while supporting multi-PDF uploads?
- ._request_json
- _post_clarification
- _saved_user_facts
- ._remove_automatic_source_markers
- test_parse_docling_layout_activity_serializes_macos_ocr
- _temporal_trace_metadata
- _view_figure
- Q: Is our Morpheus implementation better than already available tools, and if yes then how?
- Q: Is Morpheus an actual RAG agent or just a RAG chatbot?
- Q: What is missing for Morpheus to be truly agentic?
- Q: Do LangGraph/LangSmith logs represent a true ReAct agent or a Temporal workflow?
- Q: How do I wrap an agent when created inside a Temporal loop?
- Q: Do you deem it a true ReAct agent now?
- Q: How are tables processed? Are they broken into chunks?
- _workflow_id
- test_sanitize_messages_rejects_missing_null_or_unsupported_role

## God Nodes (most connected - your core abstractions)
1. `Pipe` - 36 edges
2. `_database_url()` - 36 edges
3. `_psycopg()` - 32 edges
4. `run_worker()` - 28 edges
5. `AgentWorkflow` - 28 edges
6. `process_document()` - 27 edges
7. `_run_fake_workflow()` - 25 edges
8. `generate_answer_activity()` - 23 edges
9. `AgentState` - 22 edges
10. `planner_node()` - 21 edges

## Surprising Connections (you probably didn't know these)
- `test_agent_planning_nodes_are_decorated_with_traceable()` --indirect_call--> `_create_agent_plan()`  [INFERRED]
  tests/test_observability.py → agent/nodes.py
- `test_agent_planning_nodes_are_decorated_with_traceable()` --indirect_call--> `planner_node()`  [INFERRED]
  tests/test_observability.py → agent/nodes.py
- `test_ingestion_and_mcp_client_are_decorated_with_traceable()` --indirect_call--> `process_document()`  [INFERRED]
  tests/test_observability.py → ingestion/doc_processor.py
- `test_ingestion_and_mcp_client_are_decorated_with_traceable()` --indirect_call--> `_sanitize_messages()`  [INFERRED]
  tests/test_observability.py → interfaces/openai_api.py
- `start_document_upload_job()` --uses--> `DocumentIngestionWorkflow`  [INFERRED]
  interfaces/openai_api.py → orchestration/workflows.py

## Import Cycles
- None detected.

## Communities (92 total, 8 thin omitted)

### Community 0 - "activities.py"
Cohesion: 0.08
Nodes (66): attach_existing_document_activity(), commit_document_bundle_activity(), _compact_evidence(), count_reindexable_children_activity(), execute_tool_activity(), extract_user_facts_activity(), fetch_unindexed_chunk_batch_activity(), generate_direct_answer_activity() (+58 more)

### Community 1 - "Document Preprocessor Guide"
Cohesion: 0.15
Nodes (12): Acceptance checks: is a processed item useful?, Bundle-level checks, Configuration, Data model and relationships, Document Preprocessor Guide, How to use the bundle in RAG, Known limitations and operational safeguards, Native table context (+4 more)

### Community 2 - "test_agent_graph.py"
Cohesion: 0.08
Nodes (31): planner_node(), Plan once, then re-plan from tool observations after each Temporal activity., Unit coverage for LangGraph ReAct tool-routing decisions., Non-grounded confidence must become an explicit HITL state., The graph must compile with the requested planner and tool nodes., The agent retrieves only when its plan identifies relevant chat documents., Temporal think activities must wrap one compiled agent, not rebuild it., A bounded agent must not select another tool after its maximum turns. (+23 more)

### Community 3 - "scan_user_input"
Cohesion: 0.11
Nodes (26): Groq, anonymize_pii(), GuardrailResult, _is_benign_self_profile_update(), _is_self_profile_false_positive(), _moderation_category(), _prompt_guard_blocks(), BaseModel (+18 more)

### Community 4 - "test_openwebui_pipe.py"
Cohesion: 0.12
Nodes (22): title: Morpheus RAG Agent author: Morpheus version: 1.0.0…, _body(), Any, Path, Unit coverage for the native Open WebUI Morpheus Pipe., Large-document job stages are visible before the chat workflow starts., Build a minimal Open WebUI Pipe input payload., Unsupported attachments never reach the Morpheus upload endpoint. (+14 more)

### Community 5 - "_client"
Cohesion: 0.13
Nodes (18): AsyncClient, _client(), _get_models(), _get_workflow_status(), _post_workflow(), Response, Start one durable batch from multiple multipart PDF uploads., Create an in-process asynchronous HTTP client for the gateway. (+10 more)

### Community 6 - "test_guardrails.py"
Cohesion: 0.12
Nodes (21): _groq_response(), Unit tests for the local and Groq-backed user-input guardrails., Build the minimal Groq completion shape used by the guardrails., A user's own non-sensitive work city is not a prohibited disclosure., Third-party personal-data requests remain blocked by the safeguard., Without Groq, local PII redaction remains active and no network client is built., A Groq failure produces a safe sanitized fallback instead of crashing., Supported PII and secret formats are redacted locally. (+13 more)

### Community 7 - "test_openai_api.py"
Cohesion: 0.10
Nodes (30): Path, Async route coverage for the OpenAI-compatible gateway., Start one pollable multipart upload job through the ASGI application., Document-derived assistant history cannot block a safe current user turn., A destructive historical turn cannot deny an unrelated current request., A valid multipart PDF uses the existing preprocessing and pgvector loader path., A pollable upload starts a durable workflow instead of an in-memory task., Open WebUI multi-file uploads start one child workflow per document. (+22 more)

### Community 8 - "AgentWorkflow"
Cohesion: 0.08
Nodes (28): AgentWorkflow, _explicit_memory_save_requested(), Any, Execute exactly one side-effecting operation with its own retry scope., Execute bounded decisions, isolated tools, and durable HITL resumption., Return the next unfinished MCP/native tool and its planned arguments., Gate only Tavily; calculator, fetch, and table tools stay ungated., Record one tool observation and force the next think step to re-plan. (+20 more)

### Community 9 - "_post_chat"
Cohesion: 0.33
Nodes (6): _post_chat(), Unsafe input must be rejected before a Temporal client is created., A completed Temporal workflow becomes a standard OpenAI chat response., Issue one chat-completions request through the ASGI application., test_chat_completion_guardrail_rejection(), test_chat_completion_success()

### Community 10 - "document_id_for_file"
Cohesion: 0.20
Nodes (13): document_content_sha256(), _document_id(), document_id_for_file(), Path, Return the complete SHA-256 digest for one document's bytes., Return a filename-independent identifier for exact-content deduplication., Retain the existing private identifier helper for compatibility., Path (+5 more)

### Community 11 - "state.py"
Cohesion: 0.15
Nodes (18): append_tool_observation(), compact_mcp_observation(), compact_retrieval_observation(), json_stable_evidence_key(), merge_retrieved_evidence(), normalize_retrieval_query(), Any, Primitive, bounded state passed between LangGraph decision nodes. (+10 more)

### Community 12 - "build_evaluation_set.py"
Cohesion: 0.11
Nodes (26): build_review_cases(), _default_document_id(), _fetch_rows(), import_human_review(), main(), _numeric_prompt(), Any, Path (+18 more)

### Community 13 - "nodes.py"
Cohesion: 0.12
Nodes (26): _conversation_transform_request(), _create_agent_plan(), _document_lookup_mode(), _document_overview_request(), _explicit_document_request(), _explicit_web_search_requested(), _fallback_plan(), _next_plan_action() (+18 more)

### Community 14 - "doc_processor.py"
Cohesion: 0.20
Nodes (14): _bounding_boxes(), _item_page_numbers(), Convert local documents into context-rich chunks for retrieval., Return page-aware bounding boxes from a Docling item., Return ordered, unique source pages from one Docling item's provenance., Create a header and row-safe textual representation from Docling table cells., Create token-bounded table chunks without splitting a table row., Extract canonical tables with native heading and caption context. (+6 more)

### Community 15 - "pg_engine.py"
Cohesion: 0.06
Nodes (64): Shared configuration for the application language model., attach_documents_to_session(), _child_retrieval_text(), count_reindexable_children(), _database_url(), document_ingestion_stats(), document_overview_and_join(), _embed() (+56 more)

### Community 16 - "Retrieval Guide"
Cohesion: 0.17
Nodes (11): Configuration, Data relationships, Hybrid retrieval flow, Initializing the schema, Loading a preprocessed bundle, Operational constraints, Purpose, Result contract (+3 more)

### Community 17 - "evaluate.py"
Cohesion: 0.06
Nodes (51): evaluate(), EvaluationCase, _latency_summary(), _load_cases(), main(), _metric_summary(), Any, Path (+43 more)

### Community 18 - "openai_api.py"
Cohesion: 0.29
Nodes (9): _aggregate_ingestion_progress(), _batch_workflow_ids(), DocumentUploadJobResponse, get_document_upload_job(), OpenAI-compatible HTTP gateway for the durable RAG agent workflow., Expose background PDF ingestion progress to polling user interfaces., Decode a gateway-created batch identifier without relying on process memory., Derive a batch status directly from durable child workflow query results. (+1 more)

### Community 19 - "_page_markdown_sections"
Cohesion: 0.14
Nodes (20): _asset_page_numbers(), _caption_image(), Figure, _figure_metadata(), _page_markdown_sections(), Any, ProgressCallback, Generate a dense semantic caption and return base64 PNG data for an extracted… (+12 more)

### Community 20 - "_sanitize_messages"
Cohesion: 0.15
Nodes (20): chat_completions(), _message_content(), _message_role(), Any, traceable, Validate and return one text OpenAI chat message content value., Validate and return one supported OpenAI chat message role., Screen user turns for injection and only the current turn for safety. (+12 more)

### Community 21 - "_load_evidence_by_references"
Cohesion: 0.20
Nodes (10): _display_document_name(), _load_evidence_by_references(), _page_grounded_child_text(), Remove the page-less global summary before using a child as cited evidence., Hide Open WebUI's opaque upload prefix from human-facing citations., Hydrate only selected parent, child, table, and figure records for an answer., Generated document summaries must not masquerade as page-local evidence., Citations show user filenames rather than Open WebUI's opaque stored name. (+2 more)

### Community 22 - "WorkflowStateResponse"
Cohesion: 0.18
Nodes (13): ClarificationSignalRequest, DocumentUploadResponse, get_workflow_status(), BaseModel, Return the outcome of every PDF in a single multipart upload request., Query the durable workflow state needed for UI progress and HITL prompts., Validate a human decision before it reaches a Temporal workflow., Expose the compact, durable state required by a polling UI. (+5 more)

### Community 23 - "test_doc_processor.py"
Cohesion: 0.16
Nodes (14): fixture, _decode_page_chunk(), _encoding(), _page_token_stream(), Return the tokenizer used to enforce stable chunk-size boundaries., Associate every encoded Markdown token with its source page., Decode one token slice together with its ordered source-page set., Split text into bounded token groups without discarding content. (+6 more)

### Community 24 - "export_retrieval_database"
Cohesion: 0.15
Nodes (15): _database_url(), _excel_value(), export_retrieval_database(), main(), Any, Path, Export the normalized pgvector retrieval database to an Excel workbook., Run the retrieval database exporter from the command line. (+7 more)

### Community 25 - "get"
Cohesion: 0.22
Nodes (9): FileResponse, get, list_models(), Response, Serve an uploaded PDF inline for direct in-browser page viewing., Serve the stored binary figure image directly from PostgreSQL., Return the single OpenAI-compatible model exposed by this service., view_document() (+1 more)

### Community 26 - "Orchestration Guide"
Cohesion: 0.18
Nodes (10): Configuration, Determinism rules, Human-in-the-loop fallback, MCP boundary, Orchestration Guide, Purpose, Starting the worker, User facts (+2 more)

### Community 27 - "start_document_upload_job"
Cohesion: 0.27
Nodes (10): _ingestion_batch_id(), Validate one PDF upload and persist it under an opaque local filename., Encode child ingestion workflow IDs in one durable, stateless batch identifier., Upload one or more PDFs, preprocess them, and atomically load pgvector tiers., Persist PDFs quickly and process them in a pollable background job., _save_uploaded_pdf(), start_document_upload_job(), upload_documents() (+2 more)

### Community 28 - "test_orchestration.py"
Cohesion: 0.04
Nodes (64): _attach_grounded_citations(), _coerce_valid_source_citations(), ContextSufficiency, _document_evidence_pages(), _document_evidence_pages_by_name(), _format_citation_pages(), generate_answer_activity(), _parse_citation_pages() (+56 more)

### Community 29 - "AgentState"
Cohesion: 0.10
Nodes (32): compile_agent_graph(), get_agent(), Any, Path, Build and render the bounded, side-effect-free LangGraph ReAct DAG., Return the planner-selected action for one Temporal activity invocation., Compile a pure decision graph with no database or network access., Return the process-local compiled agent used by Temporal think activities. (+24 more)

### Community 30 - "Agent Guide"
Cohesion: 0.22
Nodes (8): Agent Guide, Node Behavior, Operational Checks, Purpose, Run and Verify, Setup, State Contract, Temporal and HITL Flow

### Community 31 - "process_document"
Cohesion: 0.13
Nodes (15): _figure_ids_in_parent(), _ocrmac_options(), process_document(), traceable, Return native Apple OCR options or raise a clear unsupported-platform error., Return the unique figure IDs referenced by one parent block., Return the unique table IDs referenced by one parent block., Create the required concise, global context for every retrieval chunk. (+7 more)

### Community 32 - "_scope_document_query"
Cohesion: 0.10
Nodes (24): Expand underspecified document follow-ups before their hybrid retrieval pass., _scope_document_query(), AgentPlan, BaseModel, Structured Gemini decision for one conversational agent turn., parametrize, Planner accepts registry-backed tools instead of a fixed MCP tool literal., Planner accepts native get_full_table tool with doc_id and table_id. (+16 more)

### Community 33 - "Any"
Cohesion: 0.08
Nodes (42): _answer(), _commit_document_bundle_once(), _decision_graph(), _direct_answer(), _document_embeddings(), _document_hash(), _document_parse_after_worker_restart(), _history() (+34 more)

### Community 34 - "TypedDict"
Cohesion: 0.17
Nodes (13): DocumentMetadata, ParentBlock, ProcessedChunk, ProcessedDocument, TypedDict, Coverage and integrity checks for one normalized document bundle., Normalized parent and child records produced from one source document., A retrieval child chunk linked to normalized parent content. (+5 more)

### Community 35 - "test_pg_engine_contract.py"
Cohesion: 0.07
Nodes (31): consolidate_document_identity(), _file_sha256(), get_document_source_path(), get_figure_image_data(), _matched_table_text_for_reranking(), Path, Return only the best table match so reranking input stays bounded., Find local document file path by document ID or filename. (+23 more)

### Community 36 - "Pipe"
Cohesion: 0.17
Nodes (10): Pipe, BaseModel, Strip wrapping brackets/punctuation that markdown autolinkers glue onto URLs., Expose the durable Morpheus RAG workflow as an Open WebUI chat model., Administrator-configurable gateway connection and polling limits., Initialize Pipe settings with safe Docker Desktop defaults., Register this Pipe as a selectable model in Open WebUI., Valves (+2 more)

### Community 37 - ".pipe"
Cohesion: 0.23
Nodes (7): EventCall, EventEmitter, Recover the original question from Open WebUI's built-in RAG wrapper., Show one native Open WebUI workflow-progress status event., Emit native Open WebUI source metadata cards for cited documents., Poll one background ingestion job while emitting visible progress., Upload PDFs, run a durable workflow, and handle in-chat web-search approval.

### Community 38 - "Q: Why is Morpheus not a general chatbot with optional document context and web search?"
Cohesion: 0.50
Nodes (3): Answer, Q: Why is Morpheus not a general chatbot with optional document context and web search?, Source Nodes

### Community 39 - "mcp_client.py"
Cohesion: 0.08
Nodes (33): TypedDict, Public planning contract for one registry-backed MCP tool., ToolSpec, call_mcp_tool(), _configured_tool_registry(), _default_tool_registry(), Any, traceable (+25 more)

### Community 40 - "Any"
Cohesion: 0.20
Nodes (6): Any, Perform one bounded HTTP request and decode its JSON response., Render one compact, factual ingestion status for Open WebUI., Interpret Open WebUI confirmation results and fail closed on disconnects., Normalize Open WebUI/OpenAI message content to plain text for the gateway., Handle Open WebUI metadata tasks without starting a Morpheus workflow.

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

### Community 54 - "_conversation_retrieval_context"
Cohesion: 0.25
Nodes (8): _conversation_retrieval_context(), Remove raw attachment tags, URL links, and boilerplate from prior turn text., Extract bounded prior-turn context for an otherwise underspecified search query., _sanitize_conversation_context(), Queries targeting a specific page or figure do not get diluted by prior…, Sanitizer strips XML file attachment blocks and Markdown URLs., test_conversation_retrieval_context_skips_structural_page_queries(), test_sanitize_conversation_context_removes_attachment_xml_and_urls()

### Community 55 - "schema.sql"
Cohesion: 0.33
Nodes (10): agent_tool_results, children, documents, figure_images, figures, parents, table_chunks, tables (+2 more)

### Community 56 - "Q: What is the current confidence layer in Morpheus?"
Cohesion: 0.50
Nodes (3): Answer, Q: What is the current confidence layer in Morpheus?, Source Nodes

### Community 57 - "Q: Are the current retrieval confidence thresholds too strict and should they be reduced?"
Cohesion: 0.50
Nodes (3): Answer, Q: Are the current retrieval confidence thresholds too strict and should they be reduced?, Source Nodes

### Community 58 - "Q: How does clarification approval resume a Temporal agent workflow?"
Cohesion: 0.50
Nodes (3): Answer, Q: How does clarification approval resume a Temporal agent workflow?, Source Nodes

### Community 59 - "_history_for_user"
Cohesion: 0.13
Nodes (20): _extract_document_facts(), _extract_facts(), _history_for_user(), _load_mcp_results(), BaseModel, traceable, Hydrate stored tool payloads only while generating the answer., One durable preference or entity explicitly disclosed by a user. (+12 more)

### Community 60 - "Q: How was historical chat content prevented from causing guardrail denials?"
Cohesion: 0.50
Nodes (3): Answer, Q: How was historical chat content prevented from causing guardrail denials?, Source Nodes

### Community 62 - ".get_reindex_status"
Cohesion: 0.29
Nodes (4): Expose durable ingestion state for gateway and UI polling., Expose durable batch progress without returning child text or vectors., Expose durable HITL and bounded-turn state to a client., query

### Community 66 - "_run_fake_workflow"
Cohesion: 0.08
Nodes (24): _get_full_table_mock(), Provide a deterministic full table result double., Run the workflow with isolated activity doubles and optional HITL signals., The workflow dispatches get_full_table_activity and retains its result…, A verifier-approved borderline result should synthesize locally without Tavily., A document-plus-web plan retains compact references from both tools., Tavily never runs until approve_web_search, including explicit web plans., The workflow executes a non-Tavily MCP tool and keeps only its persisted ID. (+16 more)

### Community 67 - "Q: How are role validation and guardrail screening enforced across chat messages?"
Cohesion: 0.50
Nodes (3): Answer, Q: How are role validation and guardrail screening enforced across chat messages?, Source Nodes

### Community 68 - "_process_saved_documents"
Cohesion: 0.33
Nodes (6): _process_saved_documents(), Path, Preprocess, store, and attach saved PDFs while reporting completed work., Describe one completed PDF ingestion performed through the HTTP gateway., UploadedDocumentResult, UploadProgressCallback

### Community 69 - "_resolve_document_name"
Cohesion: 0.50
Nodes (4): _canonical_document_name(), Compare citation filenames without upload prefixes, quotes, or case differences., Map a model-cited filename onto one grounded evidence filename., _resolve_document_name()

### Community 70 - "._format_source_bubbles"
Cohesion: 0.33
Nodes (4): Keep web and PDF hrefs valid when they contain commas or wrapping brackets., Transform text citations like [Source: doc.pdf, p. 1] into clean clickable…, Bracket-wrapped or comma-containing web URLs must not keep a trailing ]., test_pipe_strips_trailing_bracket_from_web_citation_urls()

### Community 72 - "_run_batch_reindex_workflow"
Cohesion: 0.13
Nodes (15): ApplicationError, _count_reindexable_children(), _fetch_reindex_batch(), _flaky_mcp(), Fail once to prove only the MCP activity, not retrieval, is retried., Return the stable total used by the batch-reindex status query., Yield deterministic pages of child rows from a stable cursor., Fail one batch once, then prove Temporal retries only that atomic unit. (+7 more)

### Community 74 - "Q: How does durable PDF ingestion flow from the FastAPI gateway through Temporal to PostgreSQL?"
Cohesion: 0.50
Nodes (3): Answer, Q: How does durable PDF ingestion flow from the FastAPI gateway through Temporal to PostgreSQL?, Source Nodes

### Community 75 - "DocumentIngestionWorkflow"
Cohesion: 0.13
Nodes (13): BatchReindexWorkflow, DocumentIngestionWorkflow, defn, Durably parse, embed, store, and attach one uploaded document., Initialize queryable ingestion progress without process-local state., Apply one monotonic, replay-safe workflow progress update., Durably rebuild child embeddings in independent, retry-safe batches., Initialize compact, queryable reindex progress state. (+5 more)

### Community 76 - "_get_upload_job"
Cohesion: 0.33
Nodes (6): _get_upload_job(), Fetch one background upload job state through the ASGI application., Upload progress is sourced from a durable Temporal workflow query., A batch identifier remains pollable without any gateway-side job dictionary., test_upload_job_batch_status_aggregates_child_workflow_progress(), test_upload_job_status_reads_temporal_workflow_query()

### Community 77 - "Q: How does the ingestion workflow avoid Temporal payload limits while supporting multi-PDF uploads?"
Cohesion: 0.50
Nodes (3): Answer, Q: How does the ingestion workflow avoid Temporal payload limits while supporting multi-PDF uploads?, Source Nodes

### Community 78 - "._request_json"
Cohesion: 0.18
Nodes (6): Path, Return readable PDF attachments from Open WebUI's reserved files argument., Identify one Open WebUI attachment without reading its full contents., Build one gateway URL without permitting arbitrary redirect targets., Execute a JSON gateway request off the Open WebUI event loop., Submit PDFs and their owning chat identity as one multipart request.

### Community 79 - "_post_clarification"
Cohesion: 0.33
Nodes (6): _post_clarification(), Approved web search reaches the workflow signal before refreshed state is…, A completed workflow must not receive a late approval signal., Send one human-in-the-loop choice through the gateway., test_submit_clarification_rejects_non_waiting_workflow_without_signalling(), test_submit_clarification_signals_temporal_workflow()

### Community 80 - "_saved_user_facts"
Cohesion: 0.50
Nodes (4): Report persisted facts for an explicit-memory workflow test., An explicit request waits for fact persistence before returning the answer., _saved_user_facts(), test_agent_workflow_confirms_explicit_persistent_memory_save()

### Community 81 - "._remove_automatic_source_markers"
Cohesion: 0.50
Nodes (3): Remove legacy Open WebUI numeric markers from a Morpheus-owned answer., Morpheus owns visible source citations and never returns Open WebUI's [1]…, test_pipe_removes_automatic_numeric_source_markers()

### Community 82 - "test_parse_docling_layout_activity_serializes_macos_ocr"
Cohesion: 0.67
Nodes (3): Path, Apple Vision parsing never overlaps across concurrent worker activity threads., test_parse_docling_layout_activity_serializes_macos_ocr()

### Community 84 - "_view_figure"
Cohesion: 0.33
Nodes (6): Fetch stored figure image bytes through the ASGI application., A found figure image returns its stored binary bytes with image/png., Missing figure image returns HTTP 404., test_view_figure_image_returns_404_when_missing(), test_view_figure_image_returns_png_response(), _view_figure()

### Community 86 - "Q: Is our Morpheus implementation better than already available tools, and if yes then how?"
Cohesion: 0.50
Nodes (3): Answer, Q: Is our Morpheus implementation better than already available tools, and if yes then how?, Source Nodes

### Community 87 - "Q: Is Morpheus an actual RAG agent or just a RAG chatbot?"
Cohesion: 0.50
Nodes (3): Answer, Q: Is Morpheus an actual RAG agent or just a RAG chatbot?, Source Nodes

### Community 88 - "Q: What is missing for Morpheus to be truly agentic?"
Cohesion: 0.50
Nodes (3): Answer, Q: What is missing for Morpheus to be truly agentic?, Source Nodes

### Community 89 - "Q: Do LangGraph/LangSmith logs represent a true ReAct agent or a Temporal workflow?"
Cohesion: 0.50
Nodes (3): Answer, Q: Do LangGraph/LangSmith logs represent a true ReAct agent or a Temporal workflow?, Source Nodes

### Community 90 - "Q: How do I wrap an agent when created inside a Temporal loop?"
Cohesion: 0.50
Nodes (3): Answer, Q: How do I wrap an agent when created inside a Temporal loop?, Source Nodes

### Community 91 - "Q: Do you deem it a true ReAct agent now?"
Cohesion: 0.50
Nodes (3): Answer, Q: Do you deem it a true ReAct agent now?, Source Nodes

### Community 92 - "Q: How are tables processed? Are they broken into chunks?"
Cohesion: 0.50
Nodes (3): Answer, Q: How are tables processed? Are they broken into chunks?, Source Nodes

### Community 93 - "_workflow_id"
Cohesion: 0.50
Nodes (4): Create one unique workflow identity while retaining the chat scope in its name., _workflow_id(), A repeated submission in one chat must not collide with an active Temporal run., test_workflow_id_is_unique_for_each_chat_turn()

### Community 95 - "test_sanitize_messages_rejects_missing_null_or_unsupported_role"
Cohesion: 0.67
Nodes (3): parametrize, Malformed roles fail at the gateway before any guardrail or workflow call., test_sanitize_messages_rejects_missing_null_or_unsupported_role()

## Knowledge Gaps
- **93 isolated node(s):** `morpheus-v0-1`, `user_facts`, `user_sessions`, `agent_tool_results`, `Purpose` (+88 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 664 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **8 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `AgentWorkflow` connect `AgentWorkflow` to `activities.py`, `Any`, `_run_fake_workflow`, `DocumentIngestionWorkflow`, `test_orchestration.py`, `.get_reindex_status`?**
  _High betweenness centrality (0.043) - this node is a cross-community bridge._
- **Why does `_sanitize_messages()` connect `_sanitize_messages` to `scan_user_input`, `test_openai_api.py`, `mcp_client.py`, `pg_engine.py`, `openai_api.py`, `test_sanitize_messages_rejects_missing_null_or_unsupported_role`?**
  _High betweenness centrality (0.042) - this node is a cross-community bridge._
- **Why does `process_document()` connect `process_document` to `activities.py`, `TypedDict`, `_process_saved_documents`, `mcp_client.py`, `document_id_for_file`, `doc_processor.py`, `pg_engine.py`, `openai_api.py`, `_page_markdown_sections`, `test_doc_processor.py`?**
  _High betweenness centrality (0.041) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `Pipe` (e.g. with `test_pipe_removes_automatic_numeric_source_markers()` and `test_pipe_strips_trailing_bracket_from_web_citation_urls()`) actually correct?**
  _`Pipe` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Are the 24 inferred relationships involving `run_worker()` (e.g. with `attach_existing_document_activity()` and `commit_document_bundle_activity()`) actually correct?**
  _`run_worker()` has 24 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `AgentWorkflow` (e.g. with `run_worker()` and `_observe_terminal_state_during_persistence()`) actually correct?**
  _`AgentWorkflow` has 4 INFERRED edges - model-reasoned connections that need verification._
- **What connects `morpheus-v0-1`, `user_facts`, `user_sessions` to the rest of the system?**
  _93 weakly-connected nodes found - possible documentation gaps or missing edges._