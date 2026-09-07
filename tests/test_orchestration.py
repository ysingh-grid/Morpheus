"""Resilience coverage for isolated Temporal agent tool activities."""

from __future__ import annotations

import asyncio
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import patch
from uuid import uuid4

from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from orchestration.activities import (
    _compact_evidence,
    _display_document_name,
    _document_evidence_pages,
    _document_evidence_pages_by_name,
    _page_grounded_child_text,
    _source_citations_are_valid,
    generate_direct_answer_activity,
    generate_answer_activity,
    load_history_activity,
    persist_session_turn_activity,
    run_agent_graph_activity,
    run_agent_retrieval_activity,
    verify_borderline_confidence_activity,
)
import orchestration.activities as workflow_activities
from orchestration.workflows import AgentWorkflow, DocumentIngestionWorkflow
from retrieval.pg_engine import (
    _database_url,
    _psycopg,
    attach_documents_to_session,
    initialize_schema,
)

CALLS: Counter[str] = Counter()


def test_compact_evidence_accepts_retrieval_table_chunk_identifier() -> None:
    """Retrieval table chunks use table_chunk_id while hydration uses the same ID value."""
    compact = _compact_evidence(
        {
            "chunk_id": "child-1",
            "parent_id": "parent-1",
            "document_id": "document-1",
            "rrf_score": 0.1,
            "vector_distance": 0.2,
            "lexical_match": True,
            "rrf_score_margin": 0.01,
            "reranker_score": 0.9,
            "matched_table_chunks": [{"table_chunk_id": "table-1-chunk-0"}],
        }
    )

    assert compact["matched_table_chunk_ids"] == ["table-1-chunk-0"]


def test_document_evidence_pages_collects_text_table_and_figure_provenance() -> None:
    """Citation allowlists include every explicit page source and no inferred values."""
    pages = _document_evidence_pages(
        [
            {
                "page_numbers": [2],
                "parent_page_numbers": [2, 3],
                "document_name": "report.pdf",
                "matched_table_chunks": [{"page_numbers": [4]}],
                "figures": [{"bounding_boxes": [{"page_no": 5}]}],
                "tables": [{"bounding_boxes": [{"page_no": 6}]}],
            }
        ]
    )

    assert pages == {2, 3, 4, 5, 6}
    assert _document_evidence_pages_by_name(
        [
            {
                "document_name": "report.pdf",
                "page_numbers": [2],
                "parent_page_numbers": [3],
                "figures": [],
                "tables": [],
                "matched_table_chunks": [],
            }
        ]
    ) == {"report.pdf": {2, 3}}


def test_page_grounded_child_text_removes_global_summary() -> None:
    """Generated document summaries must not masquerade as page-local evidence."""
    text = (
        "Document summary: This fact may come from any page.\n\nPage-local source text."
    )

    assert _page_grounded_child_text(text) == "Page-local source text."
    assert _page_grounded_child_text("Already page-local.") == "Already page-local."


def test_display_document_name_removes_only_openwebui_upload_prefix() -> None:
    """Citations show user filenames rather than Open WebUI's opaque stored name."""
    assert (
        _display_document_name(
            "uploads/eb8a850d-0bbc-4c5f-a21c-e456689aae00_Circular.pdf"
        )
        == "Circular.pdf"
    )
    assert _display_document_name("dummy_data/annual-report.pdf") == "annual-report.pdf"


def test_source_citation_validation_rejects_missing_or_unavailable_pages() -> None:
    """Only visible citations with grounded filenames and full page ranges are accepted."""
    allowed = {"report.pdf": {12, 13}}
    assert _source_citations_are_valid(
        "Assets rose. [Source: report.pdf, pp. 12–13]", allowed
    )
    assert not _source_citations_are_valid("Assets rose.", allowed)
    assert not _source_citations_are_valid(
        "Assets rose. [Source: report.pdf, p. 14]", allowed
    )
    assert not _source_citations_are_valid(
        "Assets rose. [Source: other.pdf, p. 12]", allowed
    )
    assert not _source_citations_are_valid(
        "Assets rose. [Source: report.pdf, pp. 12–15]", allowed
    )


def test_generate_answer_repairs_missing_page_citation() -> None:
    """An uncited model draft gets one constrained repair before it is returned."""
    evidence = [
        {
            "chunk_id": "child-1",
            "parent_id": "parent-1",
            "document_id": "document-1",
            "child_text": "The total was 42.",
            "parent_text": "The total was 42.",
            "document_name": "report.pdf",
            "page_numbers": [7],
            "parent_page_numbers": [7],
            "figures": [],
            "tables": [],
            "matched_table_chunks": [],
        }
    ]
    responses = [
        SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content="The total was 42."))
            ]
        ),
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="The total was 42. [Source: report.pdf, p. 7]"
                    )
                )
            ]
        ),
    ]

    with (
        patch(
            "orchestration.activities._load_evidence_by_references",
            return_value=evidence,
        ),
        patch("orchestration.activities._load_mcp_results", return_value=[]),
        patch(
            "orchestration.activities.llm_client.chat.completions.create",
            side_effect=responses,
        ) as create,
    ):
        answer = generate_answer_activity(
            "What was the total?",
            [{"chunk_id": "child-1", "parent_id": "parent-1"}],
            [],
            [],
        )

    assert answer == "The total was 42. [Source: report.pdf, p. 7]"
    assert create.call_count == 2


@activity.defn(name="extract_user_facts_activity")
def _record_user_facts(_user_id: str, _prompt: str, _response: str) -> bool:
    """Keep workflow tests focused on agent orchestration behavior."""
    return False


@activity.defn(name="load_history_activity")
def _history(_user_id: str, _session_id: str) -> dict[str, Any]:
    """Provide compact preloaded history for deterministic workflow tests."""
    CALLS["history"] += 1
    return {"messages": [], "document_ids": ["document-1"]}


@activity.defn(name="persist_session_turn_activity")
def _persist_session(
    _user_id: str,
    _session_id: str,
    _messages: list[dict[str, Any]],
    _answer: str,
) -> None:
    """Keep resilience tests independent of PostgreSQL session storage."""
    CALLS["session"] += 1


@activity.defn(name="persist_session_turn_activity")
async def _persist_session_slow(
    _user_id: str,
    _session_id: str,
    _messages: list[dict[str, Any]],
    _answer: str,
) -> None:
    """Keep the workflow queryable after answer generation to expose status races."""
    await asyncio.sleep(0.2)


def _next_action(state: dict[str, Any]) -> dict[str, Any]:
    """Model the agent's persisted plan without invoking Gemini in workflow tests."""
    result = dict(state)
    if "agent_plan" not in result:
        if result["query"] == "direct conversation":
            tool_sequence: list[str] = []
            intent = "conversation"
            document_only = False
        elif result["query"] == "ambiguous with web":
            tool_sequence = ["hybrid_search", "mcp_search"]
            intent = "document_and_web"
            document_only = False
        elif result["query"] == "ambiguous requires approval":
            tool_sequence = ["hybrid_search"]
            intent = "document"
            document_only = False
        else:
            tool_sequence = ["hybrid_search"]
            intent = "document"
            document_only = result["query"] in {"not found"}
        result["agent_plan"] = {
            "intent": intent,
            "tool_sequence": tool_sequence,
            "document_only": document_only,
            "clarification_question": "Please clarify your document question.",
            "reason": "Deterministic workflow test plan.",
        }
    if result.get("verification_pending"):
        result["clarification_needed"] = not result.get("context_sufficient", False)
        result["verification_pending"] = False
    completed_tools = set(result.get("completed_tools", []))
    plan = result["agent_plan"]
    if result.get("iteration_count", 0) >= result.get("max_turns", 5):
        result["next_action"] = "ask_clarification"
    elif result.get("clarification_needed"):
        remaining = [
            tool for tool in plan["tool_sequence"] if tool not in completed_tools
        ]
        result["next_action"] = remaining[0] if remaining else "ask_clarification"
    elif remaining := [
        tool for tool in plan["tool_sequence"] if tool not in completed_tools
    ]:
        result["next_action"] = remaining[0]
    elif (
        plan["document_only"]
        and result.get("retrieval_response", {}).get("status") == "not_found"
    ):
        result["next_action"] = "ask_clarification"
    elif result.get("retrieved_evidence") or result.get("mcp_results"):
        result["next_action"] = "generate_answer"
    else:
        result["next_action"] = "direct_answer"
    return result


@activity.defn(name="run_agent_graph_activity")
async def _decision_graph(state: dict[str, Any]) -> dict[str, Any]:
    """Return one pure decision without calling external systems."""
    CALLS["decision"] += 1
    return _next_action(state)


@activity.defn(name="run_agent_retrieval_activity")
def _retrieval(
    query: str,
    _top_k: int,
    _document_ids: list[str],
    _document_lookup: str,
) -> dict[str, Any]:
    """Return compact references only, never full parent/table payloads."""
    CALLS["retrieval"] += 1
    if query == "not found":
        return {
            "status": "not_found",
            "message": "Not found in uploaded documents.",
            "confidence": {},
            "evidence": [],
        }
    if query in {
        "ambiguous",
        "ambiguous with web",
        "ambiguous requires approval",
        "borderline sufficient",
    }:
        return {
            "status": "clarification_needed",
            "message": "Ambiguous evidence.",
            "confidence": {"rrf_score": 0.015},
            "evidence": [{"chunk_id": "chunk-1", "parent_id": "parent-1"}],
        }
    return {
        "status": "grounded",
        "message": "Grounded evidence retrieved.",
        "confidence": {},
        "evidence": [{"chunk_id": "chunk-1", "parent_id": "parent-1"}],
    }


@activity.defn(name="verify_borderline_confidence_activity")
def _verify(
    query: str,
    _response: dict[str, Any],
    _references: list[dict[str, Any]],
    _force_verification: bool,
) -> bool:
    """Mark only the named test query as sufficient local context."""
    CALLS["verify"] += 1
    return query == "borderline sufficient"


@activity.defn(name="execute_agent_mcp_activity")
async def _mcp(_session_id: str, _query: str) -> dict[str, str]:
    """Return a compact persisted-MCP reference."""
    CALLS["mcp"] += 1
    return {"tool_result_id": "tool-1", "tool_name": "tavily_search"}


@activity.defn(name="execute_agent_mcp_activity")
async def _flaky_mcp(_session_id: str, _query: str) -> dict[str, str]:
    """Fail once to prove only the MCP activity, not retrieval, is retried."""
    CALLS["mcp"] += 1
    if CALLS["mcp"] == 1:
        raise ApplicationError("temporary MCP outage", type="McpToolError")
    return {"tool_result_id": "tool-1", "tool_name": "tavily_search"}


@activity.defn(name="generate_answer_activity")
def _answer(
    _query: str,
    _evidence_references: list[dict[str, Any]],
    _mcp_references: list[dict[str, Any]],
    _messages: list[dict[str, Any]],
) -> str:
    """Return a deterministic answer after the workflow selects its evidence."""
    CALLS["answer"] += 1
    return "Grounded answer"


@activity.defn(name="generate_direct_answer_activity")
def _direct_answer(
    _query: str,
    _messages: list[dict[str, Any]],
    _tool_errors: dict[str, str],
) -> str:
    """Return a deterministic tool-free conversational response."""
    CALLS["direct_answer"] += 1
    return "Conversational answer"


async def _run_fake_workflow(
    query: str,
    choices: tuple[str, ...] = (),
    mcp_activity: Callable[..., Any] = _mcp,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Run the workflow with isolated activity doubles and optional HITL signals."""
    CALLS.clear()
    task_queue = f"orchestration-resilience-{uuid4()}"
    activities = [
        _history,
        _decision_graph,
        _retrieval,
        _verify,
        mcp_activity,
        _answer,
        _direct_answer,
        _persist_session,
        _record_user_facts,
    ]
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        with ThreadPoolExecutor(max_workers=2) as executor:
            async with Worker(
                environment.client,
                task_queue=task_queue,
                workflows=[AgentWorkflow],
                activities=activities,
                activity_executor=executor,
            ):
                handle = await environment.client.start_workflow(
                    AgentWorkflow.run,
                    args=[query, "integration-test-user"],
                    id=f"resilience-{uuid4()}",
                    task_queue=task_queue,
                )
                paused_state: dict[str, Any] | None = None
                if choices:
                    for _ in range(20):
                        paused_state = await handle.query(
                            AgentWorkflow.get_workflow_state
                        )
                        if paused_state["status"] == "awaiting_clarification":
                            break
                        await asyncio.sleep(0.05)
                    else:
                        raise AssertionError(
                            f"Workflow never paused for clarification: {paused_state}"
                        )
                    for choice in choices:
                        await handle.signal(
                            AgentWorkflow.user_clarification_signal, choice
                        )
                return paused_state, await handle.result()


@activity.defn(name="hash_and_deduplicate_document_activity")
def _document_hash(_file_path: str) -> dict[str, Any]:
    """Return a new-document result for durable ingestion workflow coverage."""
    CALLS["document_hash"] += 1
    return {
        "document_id": "sha256-ingestion-test",
        "content_sha256": "ingestion-test",
        "filename": "ingestion-test.pdf",
        "already_ingested": False,
        "stats": {},
    }


@activity.defn(name="parse_docling_layout_activity")
def _document_parse_after_worker_restart(_file_path: str) -> dict[str, Any]:
    """Fail once mid-parse to model a worker loss before a retry resumes work."""
    CALLS["document_parse"] += 1
    if CALLS["document_parse"] == 1:
        raise ApplicationError("worker restarted during Docling parsing", type="WorkerLost")
    return {
        "bundle_reference": "file:///staging/ingestion-test.bundle.json",
        "document_id": "sha256-ingestion-test",
        "filename": "ingestion-test.pdf",
        "children": 2,
    }


@activity.defn(name="generate_embeddings_activity")
def _document_embeddings(bundle_reference: str) -> dict[str, Any]:
    """Return a compact embedding reference without putting vectors in history."""
    CALLS["document_embeddings"] += 1
    assert bundle_reference == "file:///staging/ingestion-test.bundle.json"
    return {
        "embeddings_reference": "file:///staging/ingestion-test.embeddings.json",
        "children": 2,
    }


@activity.defn(name="commit_document_bundle_activity")
def _commit_document_bundle_once(
    bundle_reference: str,
    embeddings_reference: str,
    user_id: str,
    session_id: str,
) -> dict[str, Any]:
    """Model the idempotent atomic commit boundary used after a parse retry."""
    CALLS["document_commit"] += 1
    assert bundle_reference == "file:///staging/ingestion-test.bundle.json"
    assert embeddings_reference == "file:///staging/ingestion-test.embeddings.json"
    assert (user_id, session_id) == ("user", "session")
    return {
        "filename": "ingestion-test.pdf",
        "document_id": "sha256-ingestion-test",
        "status": "ingested",
        "parents": 1,
        "figures": 0,
        "tables": 0,
        "table_chunks": 0,
        "children": 2,
    }


async def _run_document_ingestion_workflow() -> dict[str, Any]:
    """Run the durable ingestion workflow with a parse-retry activity double."""
    CALLS.clear()
    task_queue = f"document-ingestion-{uuid4()}"
    activities = [
        _document_hash,
        _document_parse_after_worker_restart,
        _document_embeddings,
        _commit_document_bundle_once,
    ]
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        with ThreadPoolExecutor(max_workers=2) as executor:
            async with Worker(
                environment.client,
                task_queue=task_queue,
                workflows=[DocumentIngestionWorkflow],
                activities=activities,
                activity_executor=executor,
            ):
                handle = await environment.client.start_workflow(
                    DocumentIngestionWorkflow.run,
                    args=["/tmp/ingestion-test.pdf", "user", "session"],
                    id=f"ingestion-{uuid4()}",
                    task_queue=task_queue,
                )
                return await handle.result()


def test_document_ingestion_workflow_retries_parse_without_duplicate_records() -> None:
    """A parse crash retries before one atomic parent/child bundle commit."""
    result = asyncio.run(_run_document_ingestion_workflow())

    assert result["status"] == "completed"
    assert result["progress"] == 100
    assert result["documents"] == [
        {
            "filename": "ingestion-test.pdf",
            "document_id": "sha256-ingestion-test",
            "status": "ingested",
            "parents": 1,
            "figures": 0,
            "tables": 0,
            "table_chunks": 0,
            "children": 2,
        }
    ]
    assert CALLS["document_parse"] == 2
    assert CALLS["document_commit"] == 1


def test_parse_docling_layout_activity_serializes_macos_ocr(tmp_path: Path) -> None:
    """Apple Vision parsing never overlaps across concurrent worker activity threads."""
    source = tmp_path / "document.pdf"
    source.write_bytes(b"%PDF-1.7 test")
    first_parse_started = Event()
    release_first_parse = Event()
    second_parse_started = Event()
    parse_calls = 0

    def parse(_path: str, progress_callback: Callable[..., Any]) -> dict[str, Any]:
        nonlocal parse_calls
        parse_calls += 1
        if parse_calls == 1:
            first_parse_started.set()
            assert release_first_parse.wait(timeout=2)
        else:
            second_parse_started.set()
        progress_callback(50, "exporting_page_layout", {"page": 1})
        return {
            "document": {"document_id": f"document-{parse_calls}"},
            "children": [],
        }

    with (
        patch("orchestration.activities.platform.system", return_value="Darwin"),
        patch("orchestration.activities.process_document", side_effect=parse),
        patch("orchestration.activities.activity.heartbeat"),
        patch("orchestration.activities.INGESTION_STAGING_DIRECTORY", tmp_path),
    ):
        first = Thread(
            target=workflow_activities.parse_docling_layout_activity,
            args=(str(source),),
        )
        second = Thread(
            target=workflow_activities.parse_docling_layout_activity,
            args=(str(source),),
        )
        first.start()
        assert first_parse_started.wait(timeout=2)
        second.start()
        assert not second_parse_started.wait(timeout=0.1)
        release_first_parse.set()
        first.join(timeout=2)
        second.join(timeout=2)

    assert parse_calls == 2
    assert second_parse_started.is_set()


async def _run_real_workflow(query: str) -> dict[str, Any]:
    """Run actual retrieval and Gemini answer synthesis through Temporal."""
    task_queue = f"orchestration-real-{uuid4()}"
    user_id = f"integration-test-user-{uuid4()}"
    session_id = f"integration-test-session-{uuid4()}"
    initialize_schema()
    psycopg = _psycopg()
    with psycopg.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id
                FROM documents
                WHERE source_path ILIKE %s
                ORDER BY id
                LIMIT 1
                """,
                ("%ifc-annual-report-2024-financials.pdf",),
            )
            row = cursor.fetchone()
    if row is None:
        raise AssertionError(
            "The IFC integration-test document is not loaded in PostgreSQL."
        )
    attach_documents_to_session(user_id, session_id, [row[0]])
    activities = [
        load_history_activity,
        run_agent_graph_activity,
        run_agent_retrieval_activity,
        verify_borderline_confidence_activity,
        generate_answer_activity,
        generate_direct_answer_activity,
        persist_session_turn_activity,
        _record_user_facts,
    ]
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        with ThreadPoolExecutor(max_workers=2) as executor:
            async with Worker(
                environment.client,
                task_queue=task_queue,
                workflows=[AgentWorkflow],
                activities=activities,
                activity_executor=executor,
            ):
                handle = await environment.client.start_workflow(
                    AgentWorkflow.run,
                    args=[query, user_id, session_id],
                    id=f"real-{uuid4()}",
                    task_queue=task_queue,
                )
                return await handle.result()


def test_agent_workflow_generates_real_answer_from_compact_references() -> None:
    """Real retrieval and answer synthesis must keep source payloads out of workflow state."""
    result = asyncio.run(
        _run_real_workflow(
            "According to the uploaded document, what were IFC's total assets in 2024?"
        )
    )
    assert result["status"] == "completed"
    assert result["retrieval"]["status"] == "grounded"
    assert result["final_answer"]
    assert result["evidence"]
    assert all("parent_text" not in reference for reference in result["evidence"])


def test_agent_workflow_returns_real_not_found_without_human_pause() -> None:
    """A no-answer result must avoid Gemini answer synthesis and MCP fallback."""
    result = asyncio.run(
        _run_real_workflow(
            "According to the uploaded document, what was IFC's Mars colonization budget?"
        )
    )
    assert result["status"] == "not_found", result
    assert result["evidence"] == []
    assert result["sources_used"] == ["pgvector"]


def test_mcp_retry_does_not_repeat_retrieval() -> None:
    """A late MCP retry must not rerun earlier retrieval or graph decisions."""
    _, result = asyncio.run(
        _run_fake_workflow("ambiguous with web", mcp_activity=_flaky_mcp)
    )
    assert result["status"] == "completed"
    assert CALLS == Counter(
        {
            "decision": 3,
            "mcp": 2,
            "history": 1,
            "retrieval": 1,
            "verify": 1,
            "answer": 1,
            "session": 1,
        }
    )


def test_borderline_sufficient_context_bypasses_hitl() -> None:
    """A verifier-approved borderline result should synthesize locally without Tavily."""
    paused_state, result = asyncio.run(_run_fake_workflow("borderline sufficient"))
    assert paused_state is None
    assert result["status"] == "completed"
    assert CALLS["verify"] == 1
    assert CALLS["mcp"] == 0


def test_combined_plan_stores_only_mcp_reference_in_workflow_response() -> None:
    """A document-plus-web plan retains compact references from both tools."""
    paused_state, result = asyncio.run(_run_fake_workflow("ambiguous with web"))
    assert paused_state is None
    assert result["sources_used"] == ["pgvector", "mcp_web_search"]
    assert result["evidence"][-1] == {
        "tool_result_id": "tool-1",
        "tool_name": "tavily_search",
    }


def test_workflow_suspends_and_resumes_on_clarification_signal() -> None:
    """Approval resumes the paused workflow and permits its planned MCP search."""
    paused_state, result = asyncio.run(
        _run_fake_workflow(
            "ambiguous requires approval", choices=("approve_web_search",)
        )
    )

    assert paused_state is not None
    assert paused_state["status"] == "awaiting_clarification"
    assert result["status"] == "completed"
    assert result["sources_used"] == ["pgvector", "mcp_web_search"]
    assert "workflow_paused_for_clarification" in result["execution_history"]
    assert "clarification_approved_web_search" in result["execution_history"]
    assert CALLS["mcp"] == 1


def test_workflow_cancellation_ends_paused_clarification_without_web_search() -> None:
    """Cancellation resolves the durable wait without executing the MCP tool."""
    paused_state, result = asyncio.run(
        _run_fake_workflow("ambiguous requires approval", choices=("cancel",))
    )

    assert paused_state is not None
    assert paused_state["status"] == "awaiting_clarification"
    assert result["status"] == "cancelled"
    assert result["final_answer"] == "Clarification/search was not approved."
    assert "clarification_cancelled" in result["execution_history"]
    assert CALLS["mcp"] == 0


def test_direct_conversation_uses_no_retrieval_or_web_tool() -> None:
    """The central agent can answer a normal chat turn with zero tools."""
    _, result = asyncio.run(_run_fake_workflow("direct conversation"))

    assert result["status"] == "completed"
    assert result["final_answer"] == "Conversational answer"
    assert result["sources_used"] == ["agent"]
    assert CALLS["retrieval"] == 0
    assert CALLS["mcp"] == 0


async def _observe_terminal_state_during_persistence() -> dict[str, Any]:
    """Query the workflow after generation but before delayed persistence finishes."""
    task_queue = f"terminal-state-{uuid4()}"
    activities = [
        _history,
        _decision_graph,
        _retrieval,
        _verify,
        _mcp,
        _answer,
        _direct_answer,
        _persist_session_slow,
        _record_user_facts,
    ]
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        with ThreadPoolExecutor(max_workers=2) as executor:
            async with Worker(
                environment.client,
                task_queue=task_queue,
                workflows=[AgentWorkflow],
                activities=activities,
                activity_executor=executor,
            ):
                handle = await environment.client.start_workflow(
                    AgentWorkflow.run,
                    args=["direct conversation", "terminal-state-user"],
                    id=f"terminal-state-{uuid4()}",
                    task_queue=task_queue,
                )
                for _ in range(50):
                    state = await handle.query(AgentWorkflow.get_workflow_state)
                    if state["status"] == "completed":
                        return state
                    await asyncio.sleep(0.01)
                raise AssertionError("Workflow did not publish completed status.")


def test_completed_status_always_publishes_final_answer_atomically() -> None:
    """UI polling must never observe completed with an empty generated answer."""
    state = asyncio.run(_observe_terminal_state_during_persistence())

    assert state["final_answer"] == "Conversational answer"
