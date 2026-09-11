# Graph Report - Morpheus-v0.1  (2026-09-07)

## Corpus Check
- 64 files · ~69,648 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1075 nodes · 2065 edges · 83 communities (74 shown, 9 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 143 edges (avg confidence: 0.87)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `60181123`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- worker.py
- Document Preprocessor Guide
- process_document
- _ingestion_batch_id
- Pipe
- test_openai_api.py
- _database_url
- _upload_pdf
- DocumentIngestionWorkflow
- openai_api.py
- document_id_for_file
- doc_processor.py
- build_evaluation_set.py
- TypedDict
- guardrails.py
- test_agent_graph.py
- Retrieval Guide
- evaluate.py
- SimpleNamespace
- _page_markdown_sections
- _assess_confidence
- activities.py
- _figure_metadata
- test_doc_processor.py
- export_retrieval_database
- nodes.py
- Orchestration Guide
- _process_saved_documents
- test_orchestration.py
- AgentState
- Agent Guide
- .run
- _create_agent_plan
- RetrievalResponse
- pg_engine.py
- test_observability.py
- workflows.py
- test_pg_engine_contract.py
- Q: Why is Morpheus not a general chatbot with optional document context and web search?
- mcp_client.py
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
- generate_answer_activity
- schema.sql
- Q: What is the current confidence layer in Morpheus?
- Q: Are the current retrieval confidence thresholds too strict and should they be reduced?
- Q: How does clarification approval resume a Temporal agent workflow?
- _history_for_user
- Q: How was historical chat content prevented from causing guardrail denials?
- test_imports_use_correct_docling_and_no_banned_fallbacks
- _observe_terminal_state_during_persistence
- interfaces/__init__.py
- orchestration/__init__.py
- retrieval/__init__.py
- _run_fake_workflow
- Q: How are role validation and guardrail screening enforced across chat messages?
- Any
- DocumentUploadJobResponse
- verify_borderline_confidence_activity
- _embed
- _run_batch_reindex_workflow
- ApplicationError
- Q: How does durable PDF ingestion flow from the FastAPI gateway through Temporal to PostgreSQL?
- test_parse_docling_layout_activity_serializes_macos_ocr
- trigger_reindex.py
- Q: How does the ingestion workflow avoid Temporal payload limits while supporting multi-PDF uploads?
- _workflow_id
- _decision_graph
- _saved_user_facts
- _temporal_trace_metadata
- test_document_ingestion_workflow_retries_parse_without_duplicate_records

## God Nodes (most connected - your core abstractions)
1. `_database_url()` - 33 edges
2. `Pipe` - 30 edges
3. `_psycopg()` - 29 edges
4. `process_document()` - 27 edges
5. `run_worker()` - 27 edges
6. `_run_fake_workflow()` - 23 edges
7. `AgentState` - 21 edges
8. `_non_retryable()` - 21 edges
9. `execute_tool_activity()` - 21 edges
10. `ingest_bundle()` - 21 edges

## Surprising Connections (you probably didn't know these)
- `test_agent_planning_nodes_are_decorated_with_traceable()` --indirect_call--> `planner_node()`  [INFERRED]
  tests/test_observability.py → agent/nodes.py
- `test_ingestion_and_mcp_client_are_decorated_with_traceable()` --indirect_call--> `_sanitize_messages()`  [INFERRED]
  tests/test_observability.py → interfaces/openai_api.py
- `start_document_upload_job()` --uses--> `DocumentIngestionWorkflow`  [INFERRED]
  interfaces/openai_api.py → orchestration/workflows.py
- `start_document_upload_job()` --indirect_call--> `attach_documents_to_session()`  [INFERRED]
  interfaces/openai_api.py → retrieval/pg_engine.py
- `_run_real_workflow()` --indirect_call--> `run_agent_retrieval_activity()`  [INFERRED]
  tests/test_orchestration.py → orchestration/activities.py

## Import Cycles
- None detected.

## Communities (83 total, 9 thin omitted)

### Community 0 - "worker.py"
Cohesion: 0.17
Nodes (15): attach_existing_document_activity(), count_reindexable_children_activity(), fetch_unindexed_chunk_batch_activity(), Load the total number of child rows for reindex workflow progress reporting., Fetch the next stable child slice for a full embedding rebuild., Embed and atomically update one batch, heartbeating sub-batch progress., Attach a deduplicated document to the requesting chat session., reindex_chunk_batch_activity() (+7 more)

### Community 1 - "Document Preprocessor Guide"
Cohesion: 0.15
Nodes (12): Acceptance checks: is a processed item useful?, Bundle-level checks, Configuration, Data model and relationships, Document Preprocessor Guide, How to use the bundle in RAG, Known limitations and operational safeguards, Native table context (+4 more)

### Community 2 - "process_document"
Cohesion: 0.14
Nodes (14): _figure_ids_in_parent(), _ocrmac_options(), process_document(), traceable, Return native Apple OCR options or raise a clear unsupported-platform error., Return the unique figure IDs referenced by one parent block., Return the unique table IDs referenced by one parent block., Create the required concise, global context for every retrieval chunk. (+6 more)

### Community 3 - "_ingestion_batch_id"
Cohesion: 0.50
Nodes (4): _ingestion_batch_id(), Encode child ingestion workflow IDs in one durable, stateless batch identifier., A batch identifier remains pollable without any gateway-side job dictionary., test_upload_job_batch_status_aggregates_child_workflow_progress()

### Community 4 - "Pipe"
Cohesion: 0.05
Nodes (50): EventCall, EventEmitter, Pipe, Any, BaseModel, Path, title: Morpheus RAG Agent author: Morpheus version: 1.0.0…, Recover the original question from Open WebUI's built-in RAG wrapper. (+42 more)

### Community 5 - "test_openai_api.py"
Cohesion: 0.06
Nodes (46): AsyncClient, Response, _client(), _get_models(), _get_upload_job(), _get_workflow_status(), _post_chat(), _post_clarification() (+38 more)

### Community 6 - "_database_url"
Cohesion: 0.18
Nodes (16): _database_url(), hybrid_search_and_join(), initialize_schema(), Run hybrid retrieval, optionally retaining ambiguous candidates for…, Return the PostgreSQL connection URL or fail before opening a connection., Create the pgvector extension, relational tables, and retrieval indexes., _assert_persisted_two_tier_records(), _bundle() (+8 more)

### Community 7 - "_upload_pdf"
Cohesion: 0.14
Nodes (17): Path, Start one pollable multipart upload job through the ASGI application., A valid multipart PDF uses the existing preprocessing and pgvector loader path., A pollable upload starts a durable workflow instead of an in-memory task., Open WebUI multi-file uploads start one child workflow per document., An in-flight duplicate upload remains pollable rather than returning a false…, The upload boundary rejects non-PDF content before expensive document…, Repeated attachment delivery must reuse PostgreSQL data without rerunning… (+9 more)

### Community 8 - "DocumentIngestionWorkflow"
Cohesion: 0.10
Nodes (17): BatchReindexWorkflow, DocumentIngestionWorkflow, Any, defn, Durably parse, embed, store, and attach one uploaded document., Initialize queryable ingestion progress without process-local state., Expose durable ingestion state for gateway and UI polling., Apply one monotonic, replay-safe workflow progress update. (+9 more)

### Community 9 - "openai_api.py"
Cohesion: 0.14
Nodes (26): get, chat_completions(), get_workflow_status(), list_models(), _message_content(), _message_role(), Any, traceable (+18 more)

### Community 10 - "document_id_for_file"
Cohesion: 0.20
Nodes (13): document_content_sha256(), _document_id(), document_id_for_file(), Path, Return the complete SHA-256 digest for one document's bytes., Return a filename-independent identifier for exact-content deduplication., Retain the existing private identifier helper for compatibility., Path (+5 more)

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
Cohesion: 0.08
Nodes (37): Groq, anonymize_pii(), GuardrailResult, _moderation_category(), _prompt_guard_blocks(), BaseModel, Local PII redaction and Groq-backed user-input guardrails., Extract Llama Guard's category code from its unsafe response. (+29 more)

### Community 15 - "test_agent_graph.py"
Cohesion: 0.17
Nodes (15): planner_node(), Let Gemini plan the turn, then select one bounded next action., Unit coverage for LangGraph ReAct tool-routing decisions., The agent retrieves only when its plan identifies relevant chat documents., The graph must compile with the requested planner and tool nodes., A bounded agent must not select another tool after its maximum turns., Direct web-search authorization must not be blocked by document retrieval…, One turn may use both session documents and web evidence before synthesis. (+7 more)

### Community 16 - "Retrieval Guide"
Cohesion: 0.17
Nodes (11): Configuration, Data relationships, Hybrid retrieval flow, Initializing the schema, Loading a preprocessed bundle, Operational constraints, Purpose, Result contract (+3 more)

### Community 17 - "evaluate.py"
Cohesion: 0.13
Nodes (24): evaluate(), EvaluationCase, _latency_summary(), _load_cases(), main(), _metric_summary(), Any, Path (+16 more)

### Community 18 - "SimpleNamespace"
Cohesion: 0.12
Nodes (20): ContextSufficiency, BaseModel, One durable preference or entity explicitly disclosed by a user., Structured output persisted by the user-fact activity., Structured borderline-confidence assessment for retrieved context., UserFact, UserFactExtraction, SimpleNamespace (+12 more)

### Community 19 - "_page_markdown_sections"
Cohesion: 0.23
Nodes (12): _asset_page_numbers(), Figure, _page_markdown_sections(), Return source pages recorded in a figure or table bounding-box list., Replace Docling's image placeholders with the generated figure captions., Replace canonical tables in document Markdown with stable table references., Export structured Markdown per source page before token chunking., One captioned figure and its source-document coordinates. (+4 more)

### Community 20 - "_assess_confidence"
Cohesion: 0.12
Nodes (20): _assess_confidence(), Assess whether the strongest RRF candidate is grounded enough to answer., Path, Unit coverage for retrieval benchmark metric calculations., A strongly matched table row is not rejected because adjacent rows rank closely., Prevent an annotation-ready set from being evaluated before human sign-off., Calculate recall, MRR, and nDCG for found and missed ground-truth results., Report stable latency summaries for a small local benchmark sample. (+12 more)

### Community 21 - "activities.py"
Cohesion: 0.12
Nodes (37): commit_document_bundle_activity(), _compact_evidence(), execute_tool_activity(), generate_direct_answer_activity(), generate_embeddings_activity(), hash_and_deduplicate_document_activity(), ingest_document_activity(), _is_borderline_confidence() (+29 more)

### Community 22 - "_figure_metadata"
Cohesion: 0.29
Nodes (8): _caption_image(), _figure_metadata(), Any, ProgressCallback, Generate a dense semantic caption for a Docling-extracted image., Caption each extracted figure and retain its page-level bounding boxes., Publish bounded ingestion progress without coupling processing to an interface., _report_progress()

### Community 23 - "test_doc_processor.py"
Cohesion: 0.13
Nodes (17): fixture, _decode_page_chunk(), _encoding(), _page_token_stream(), Return the tokenizer used to enforce stable chunk-size boundaries., Associate every encoded Markdown token with its source page., Decode one token slice together with its ordered source-page set., Split text into bounded token groups without discarding content. (+9 more)

### Community 24 - "export_retrieval_database"
Cohesion: 0.15
Nodes (15): _database_url(), _excel_value(), export_retrieval_database(), main(), Any, Path, Export the normalized pgvector retrieval database to an Excel workbook., Run the retrieval database exporter from the command line. (+7 more)

### Community 25 - "nodes.py"
Cohesion: 0.18
Nodes (13): _document_lookup_mode(), _document_overview_request(), _explicit_document_request(), _explicit_web_search_requested(), _fallback_plan(), LangGraph planning and routing nodes for the conversational agent., Infer a retrieval policy from explicit structural cues in the user query., Return a conservative tool plan if Gemini planning is temporarily unavailable. (+5 more)

### Community 26 - "Orchestration Guide"
Cohesion: 0.18
Nodes (10): Configuration, Determinism rules, Human-in-the-loop fallback, MCP boundary, Orchestration Guide, Purpose, Starting the worker, User facts (+2 more)

### Community 27 - "_process_saved_documents"
Cohesion: 0.12
Nodes (21): ClarificationSignalRequest, DocumentUploadResponse, _process_saved_documents(), BaseModel, Path, Validate one PDF upload and persist it under an opaque local filename., Preprocess, store, and attach saved PDFs while reporting completed work., Upload one or more PDFs, preprocess them, and atomically load pgvector tiers. (+13 more)

### Community 28 - "test_orchestration.py"
Cohesion: 0.06
Nodes (35): Resilience coverage for isolated Temporal agent tool activities., The calculator MCP tool defaults to uvx and mcp-server-calculator without…, The fetch MCP tool resolves to uvx mcp-server-fetch with a url parameter., Real retrieval and answer synthesis must keep source payloads out of workflow…, A no-answer result must avoid Gemini answer synthesis and MCP fallback., execute_tool_activity invokes call_mcp_tool with server_tool_name if defined., The get_full_table tool is declared in the registry with doc_id and table_id…, An attempt to query an unattached document raises UnauthorizedDocumentAccess. (+27 more)

### Community 29 - "AgentState"
Cohesion: 0.13
Nodes (23): compile_agent_graph(), Any, Path, Build and render the bounded, side-effect-free LangGraph ReAct DAG., Return the planner-selected action for one Temporal activity invocation., Compile a pure ReAct decision graph with no database or network access., Render the compiled ReAct DAG and optionally write it to a PNG file., render_graph_png() (+15 more)

### Community 30 - "Agent Guide"
Cohesion: 0.22
Nodes (8): Agent Guide, Node Behavior, Operational Checks, Purpose, Run and Verify, Setup, State Contract, Temporal and HITL Flow

### Community 31 - ".run"
Cohesion: 0.15
Nodes (11): extract_user_facts_activity(), Extract explicitly stated user facts and upsert them into PostgreSQL., AgentWorkflow, Execute bounded decisions, isolated tools, and durable HITL resumption., Persist explicit user facts without delaying the answer response., Return compact references so Temporal never transports raw source payloads., Run one tool per activity so retries never replay prior side effects., Initialize durable, replay-safe workflow state. (+3 more)

### Community 32 - "_create_agent_plan"
Cohesion: 0.10
Nodes (28): _conversation_retrieval_context(), _conversation_transform_request(), _create_agent_plan(), Extract bounded prior-turn context for an otherwise underspecified search query., Expand underspecified document follow-ups before their hybrid retrieval pass., Ask Gemini to choose zero, one, or multiple tools for the current turn., Recognize follow-ups answerable entirely from a prior assistant response., _scope_document_query() (+20 more)

### Community 33 - "RetrievalResponse"
Cohesion: 0.29
Nodes (7): GroundedEvidence, TypedDict, One reranked child hit with its normalized source evidence., Calibrated quality signals for the strongest RRF candidate., User-facing retrieval result with evidence only when it passes confidence…, RetrievalConfidence, RetrievalResponse

### Community 34 - "pg_engine.py"
Cohesion: 0.11
Nodes (29): attach_documents_to_session(), _child_retrieval_text(), consolidate_document_identity(), count_reindexable_children(), document_ingestion_stats(), fetch_reindexable_child_batch(), _file_sha256(), ingest_bundle() (+21 more)

### Community 35 - "test_observability.py"
Cohesion: 0.15
Nodes (14): Shared configuration for the application language model., document_overview_and_join(), get_full_table(), Load stored summaries and opening parents without applying semantic rank gates., Retrieve full normalized table content and metadata by document and table ID., Unit tests verifying LangSmith observability across all services and tools., The central OpenAI/Gemini client is wrapped by langsmith.wrappers.wrap_openai., Core retrieval entry points are registered as LangSmith traceable operations. (+6 more)

### Community 36 - "workflows.py"
Cohesion: 0.15
Nodes (15): get_full_table_activity(), _is_openwebui_utility_prompt(), load_history_activity(), persist_session_turn_activity(), Identify Open WebUI metadata-generation prompts that are not user turns., Execute one bounded, side-effect-free LangGraph decision pass., Load history and document scope separately from agent reasoning retries., Upsert a compact, already-sanitized summary of the latest chat turn. (+7 more)

### Community 37 - "test_pg_engine_contract.py"
Cohesion: 0.13
Nodes (15): _flashrank_rerank(), _matched_table_text_for_reranking(), Rerank parent evidence with FlashRank after the SQL retrieval pass., Return only the best table match so reranking input stays bounded., Static contract checks for the pgvector retrieval implementation., Keep the required pgvector and FTS indexes from regressing., Require RRF CTEs and relational joins in the one retrieval query., Serialize values in the format accepted by PostgreSQL's vector type. (+7 more)

### Community 38 - "Q: Why is Morpheus not a general chatbot with optional document context and web search?"
Cohesion: 0.50
Nodes (3): Answer, Q: Why is Morpheus not a general chatbot with optional document context and web search?, Source Nodes

### Community 39 - "mcp_client.py"
Cohesion: 0.10
Nodes (29): _planned_action(), Any, Select the next unfinished tool or response action from the agent's plan., TypedDict, Primitive, bounded state passed between LangGraph decision nodes., Public planning contract for one registry-backed MCP tool., ToolSpec, call_mcp_tool() (+21 more)

### Community 40 - "verify_groundedness_node"
Cohesion: 0.29
Nodes (7): ask_clarification_node(), traceable, Apply confidence-verifier output without performing an LLM call here., Return a safe clarification or no-answer response without external I/O., verify_groundedness_node(), Non-grounded confidence must become an explicit HITL state., test_verify_groundedness_node_requests_clarification_for_weak_retrieval()

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

### Community 54 - "generate_answer_activity"
Cohesion: 0.22
Nodes (10): _document_evidence_pages(), _document_evidence_pages_by_name(), generate_answer_activity(), Collect every page number that the answer is allowed to cite., Group explicit page provenance by source filename for visible answer citations., Require visible source citations and reject unavailable document-page…, Hydrate selected tool results and let the agent synthesize one answer., _source_citations_are_valid() (+2 more)

### Community 55 - "schema.sql"
Cohesion: 0.36
Nodes (9): agent_tool_results, children, documents, figures, parents, table_chunks, tables, user_facts (+1 more)

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
Cohesion: 0.18
Nodes (11): _extract_document_facts(), _extract_facts(), _history_for_user(), _load_mcp_results(), traceable, Hydrate stored tool payloads only while generating the answer., Extract durable user profile, preference, project, and domain facts from the…, Compact conversational memory and uploaded-document scope for one chat. (+3 more)

### Community 60 - "Q: How was historical chat content prevented from causing guardrail denials?"
Cohesion: 0.50
Nodes (3): Answer, Q: How was historical chat content prevented from causing guardrail denials?, Source Nodes

### Community 62 - "_observe_terminal_state_during_persistence"
Cohesion: 0.14
Nodes (14): _answer(), _direct_answer(), _observe_terminal_state_during_persistence(), Query the workflow after generation but before delayed persistence finishes., UI polling must never observe completed with an empty generated answer., Keep workflow tests focused on agent orchestration behavior., Return compact references only, never full parent/table payloads., Mark only the named test query as sufficient local context. (+6 more)

### Community 66 - "_run_fake_workflow"
Cohesion: 0.10
Nodes (20): _get_full_table_mock(), The workflow dispatches get_full_table_activity and retains its result…, A verifier-approved borderline result should synthesize locally without Tavily., A document-plus-web plan retains compact references from both tools., The workflow executes a non-Tavily MCP tool and keeps only its persisted ID., Approval resumes the paused workflow and permits its planned MCP search., Cancellation resolves the durable wait without executing the MCP tool., The central agent can answer a normal chat turn with zero tools. (+12 more)

### Community 67 - "Q: How are role validation and guardrail screening enforced across chat messages?"
Cohesion: 0.50
Nodes (3): Answer, Q: How are role validation and guardrail screening enforced across chat messages?, Source Nodes

### Community 68 - "Any"
Cohesion: 0.14
Nodes (22): _commit_document_bundle_once(), _document_embeddings(), _document_hash(), _document_parse_after_worker_restart(), _history(), _mcp(), _persist_session(), _persist_session_slow() (+14 more)

### Community 69 - "DocumentUploadJobResponse"
Cohesion: 0.29
Nodes (8): _aggregate_ingestion_progress(), _batch_workflow_ids(), DocumentUploadJobResponse, get_document_upload_job(), Decode a gateway-created batch identifier without relying on process memory., Derive a batch status directly from durable child workflow query results., Query the durable Temporal workflow state for one PDF upload job., Expose background PDF ingestion progress to polling user interfaces.

### Community 70 - "verify_borderline_confidence_activity"
Cohesion: 0.25
Nodes (8): _display_document_name(), _load_evidence_by_references(), _page_grounded_child_text(), Remove the page-less global summary before using a child as cited evidence., Hide Open WebUI's opaque upload prefix from human-facing citations., Use Gemini for borderline hits or mandatory document-only sufficiency checks., Hydrate only selected parent, child, table, and figure records for an answer., verify_borderline_confidence_activity()

### Community 71 - "_embed"
Cohesion: 0.32
Nodes (8): _embed(), ProgressCallback, traceable, Generate 1,536-dimensional Gemini embeddings through the shared client., Rebuild existing child embeddings from page-local retrieval text., Atomically replace embeddings for one ID-ordered, retry-safe child batch., reindex_child_embedding_batch(), reindex_child_embeddings()

### Community 72 - "_run_batch_reindex_workflow"
Cohesion: 0.25
Nodes (8): _count_reindexable_children(), _fetch_reindex_batch(), Return the stable total used by the batch-reindex status query., Yield deterministic pages of child rows from a stable cursor., Execute the reindex workflow against local retry-aware activity doubles., Network retries preserve the cursor and commit every child ID exactly once., _run_batch_reindex_workflow(), test_batch_reindex_workflow_retries_only_failed_batch_without_duplicate_updates()

### Community 73 - "ApplicationError"
Cohesion: 0.29
Nodes (7): ApplicationError, _flaky_mcp(), Fail one batch once, then prove Temporal retries only that atomic unit., A late MCP retry must not rerun earlier retrieval or graph decisions., Fail once to prove only the MCP activity, not retrieval, is retried., _reindex_batch_after_network_drop(), test_mcp_retry_does_not_repeat_retrieval()

### Community 74 - "Q: How does durable PDF ingestion flow from the FastAPI gateway through Temporal to PostgreSQL?"
Cohesion: 0.50
Nodes (3): Answer, Q: How does durable PDF ingestion flow from the FastAPI gateway through Temporal to PostgreSQL?, Source Nodes

### Community 75 - "test_parse_docling_layout_activity_serializes_macos_ocr"
Cohesion: 0.67
Nodes (3): Path, Apple Vision parsing never overlaps across concurrent worker activity threads., test_parse_docling_layout_activity_serializes_macos_ocr()

### Community 76 - "trigger_reindex.py"
Cohesion: 0.40
Nodes (5): main(), Start a durable Temporal workflow that rebuilds every child embedding., Start one batch reindex workflow and return its durable execution ID., Parse CLI options and launch the durable batch reindex workflow., trigger_reindex()

### Community 77 - "Q: How does the ingestion workflow avoid Temporal payload limits while supporting multi-PDF uploads?"
Cohesion: 0.50
Nodes (3): Answer, Q: How does the ingestion workflow avoid Temporal payload limits while supporting multi-PDF uploads?, Source Nodes

### Community 78 - "_workflow_id"
Cohesion: 0.50
Nodes (4): Create one unique workflow identity while retaining the chat scope in its name., _workflow_id(), A repeated submission in one chat must not collide with an active Temporal run., test_workflow_id_is_unique_for_each_chat_turn()

### Community 79 - "_decision_graph"
Cohesion: 0.50
Nodes (4): _decision_graph(), _next_action(), Model the agent's persisted plan without invoking Gemini in workflow tests., Return one pure decision without calling external systems.

### Community 80 - "_saved_user_facts"
Cohesion: 0.50
Nodes (4): Report persisted facts for an explicit-memory workflow test., An explicit request waits for fact persistence before returning the answer., _saved_user_facts(), test_agent_workflow_confirms_explicit_persistent_memory_save()

## Knowledge Gaps
- **79 isolated node(s):** `morpheus-v0-1`, `user_facts`, `user_sessions`, `agent_tool_results`, `Purpose` (+74 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 569 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **9 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `_database_url()` connect `_database_url` to `pg_engine.py`, `test_observability.py`, `workflows.py`, `verify_borderline_confidence_activity`, `_embed`, `build_evaluation_set.py`, `evaluate.py`, `activities.py`, `_history_for_user`, `test_orchestration.py`, `.run`?**
  _High betweenness centrality (0.047) - this node is a cross-community bridge._
- **Why does `process_document()` connect `process_document` to `test_observability.py`, `openai_api.py`, `document_id_for_file`, `doc_processor.py`, `TypedDict`, `_page_markdown_sections`, `activities.py`, `_figure_metadata`, `test_doc_processor.py`, `_process_saved_documents`?**
  _High betweenness centrality (0.035) - this node is a cross-community bridge._
- **Why does `_sanitize_messages()` connect `openai_api.py` to `process_document`, `test_observability.py`, `test_openai_api.py`, `guardrails.py`?**
  _High betweenness centrality (0.031) - this node is a cross-community bridge._
- **Are the 24 inferred relationships involving `run_worker()` (e.g. with `attach_existing_document_activity()` and `commit_document_bundle_activity()`) actually correct?**
  _`run_worker()` has 24 INFERRED edges - model-reasoned connections that need verification._
- **What connects `morpheus-v0-1`, `user_facts`, `user_sessions` to the rest of the system?**
  _79 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `process_document` be split into smaller, more focused modules?**
  _Cohesion score 0.14285714285714285 - nodes in this community are weakly interconnected._
- **Should `Pipe` be split into smaller, more focused modules?**
  _Cohesion score 0.05115089514066496 - nodes in this community are weakly interconnected._