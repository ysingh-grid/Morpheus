"""Resilience coverage for isolated Temporal agent tool activities."""

from __future__ import annotations

import asyncio
import json
import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest
from openai import RateLimitError
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
    execute_tool_activity,
    generate_direct_answer_activity,
    generate_answer_activity,
    get_full_table_activity,
    load_history_activity,
    persist_session_turn_activity,
    run_agent_graph_activity,
    run_agent_retrieval_activity,
    reindex_chunk_batch_activity,
    summarize_session_history_activity,
    verify_borderline_confidence_activity,
)
import orchestration.activities as workflow_activities
from orchestration.workflows import AgentWorkflow, BatchReindexWorkflow, DocumentIngestionWorkflow
from agent.nodes import load_history_node
from orchestration.mcp_client import resolve_mcp_tool
from retrieval.pg_engine import (
    _database_url,
    _psycopg,
    attach_documents_to_session,
    initialize_schema,
)

CALLS: Counter[str] = Counter()
COMMITTED_REINDEX_IDS: list[str] = []


def test_reindex_chunk_batch_activity_retries_rate_limits_before_writing() -> None:
    """A rate-limited embedding attempt backs off and retries the same safe batch."""
    rate_limit = RateLimitError(
        "rate limited",
        response=httpx.Response(
            429, request=httpx.Request("POST", "https://example.invalid/embeddings")
        ),
        body=None,
    )
    chunks = [
        {"id": "child-1", "retrieval_text": "first"},
        {"id": "child-2", "retrieval_text": "second"},
    ]

    with (
        patch(
            "orchestration.activities.reindex_child_embedding_batch",
            side_effect=[rate_limit, "child-2"],
        ) as reindex,
        patch("orchestration.activities.time.sleep") as sleep,
        patch("orchestration.activities.activity.heartbeat") as heartbeat,
    ):
        last_processed_id = reindex_chunk_batch_activity(chunks)

    assert last_processed_id == "child-2"
    assert reindex.call_count == 2
    sleep.assert_called_once_with(1)
    assert any(
        call.args[0]["stage"] == "reindex_rate_limited" for call in heartbeat.call_args_list
    )


def test_calculator_is_a_registered_secondary_mcp_tool() -> None:
    """A separately configured calculator server resolves through the common registry."""
    with patch.dict(
        os.environ,
        {
            "CALCULATOR_MCP_SERVER_COMMAND": "calculator-mcp",
            "CALCULATOR_MCP_SERVER_ARGS": "--stdio",
            "CALCULATOR_MCP_TIMEOUT_SECONDS": "12",
        },
        clear=False,
    ):
        calculator = resolve_mcp_tool("calculator")

    assert calculator["command"] == "calculator-mcp"
    assert calculator["args"] == ["--stdio"]
    assert calculator["spec"]["timeout_seconds"] == 12
    assert calculator["spec"]["parameters"]["required"] == ["expression"]


def test_calculator_default_command_and_args() -> None:
    """The calculator MCP tool defaults to uvx and mcp-server-calculator without overrides."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("CALCULATOR_MCP_SERVER_COMMAND", None)
        os.environ.pop("CALCULATOR_MCP_SERVER_ARGS", None)
        os.environ.pop("CALCULATOR_MCP_TIMEOUT_SECONDS", None)
        calculator = resolve_mcp_tool("calculator")

    assert calculator["command"] == "uvx"
    assert calculator["args"] == ["mcp-server-calculator"]
    assert calculator["spec"]["timeout_seconds"] == 10


def test_get_full_table_is_a_registered_native_tool() -> None:
    """The get_full_table tool is declared in the registry with doc_id and table_id parameters."""
    tool = resolve_mcp_tool("get_full_table")
    assert tool["spec"]["name"] == "get_full_table"
    assert tool["spec"]["parameters"]["required"] == ["doc_id", "table_id"]
    assert tool["command"] == "native"


def test_get_full_table_activity_rejects_unattached_document() -> None:
    """An attempt to query an unattached document raises UnauthorizedDocumentAccess."""
    with pytest.raises(ApplicationError) as exception:
        workflow_activities.get_full_table_activity(
            "session-1",
            "doc-unauthorized",
            "table-1",
            ["doc-allowed-1", "doc-allowed-2"],
        )
    assert exception.value.type == "UnauthorizedDocumentAccess"
    assert "not attached to this chat session" in str(exception.value)


def test_get_full_table_activity_persists_reference() -> None:
    """A valid full table query fetches the markdown and persists an agent_tool_results row."""
    cursor = MagicMock()
    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    psycopg = MagicMock()
    psycopg.connect.return_value.__enter__.return_value = connection
    fake_table = {
        "doc_id": "doc-1",
        "table_id": "table-1",
        "markdown": "| Col A | Col B |\n| --- | --- |\n| 1 | 2 |",
        "heading": "Balance Sheet",
        "caption": "Consolidated statements",
        "context": "Financial section",
        "row_count": 2,
        "column_count": 2,
    }

    with (
        patch("orchestration.activities._psycopg", return_value=psycopg),
        patch("orchestration.activities.get_full_table", return_value=fake_table),
    ):
        reference = workflow_activities.get_full_table_activity(
            "session-1", "doc-1", "table-1", ["doc-1"]
        )

    assert reference["tool_name"] == "get_full_table"
    assert reference["tool_result_id"]
    statement, params = cursor.execute.call_args.args
    assert "INSERT INTO agent_tool_results" in statement
    assert params[1:3] == ("session-1", "get_full_table")
    saved_result = json.loads(params[3])
    assert saved_result["markdown"] == fake_table["markdown"]
    assert saved_result["row_count"] == 2


def test_execute_tool_activity_routes_get_full_table() -> None:
    """execute_tool_activity inspects user_sessions and executes get_full_table."""
    session_cursor = MagicMock()
    session_cursor.fetchone.return_value = {"document_ids": ["doc-1"]}
    session_conn = MagicMock()
    session_conn.cursor.return_value.__enter__.return_value = session_cursor

    insert_cursor = MagicMock()
    insert_conn = MagicMock()
    insert_conn.cursor.return_value.__enter__.return_value = insert_cursor

    psycopg = MagicMock()
    psycopg.connect.side_effect = [
        MagicMock(__enter__=MagicMock(return_value=session_conn)),
        MagicMock(__enter__=MagicMock(return_value=insert_conn)),
    ]
    fake_table = {
        "doc_id": "doc-1",
        "table_id": "table-1",
        "markdown": "| Col A |",
        "heading": "H",
        "caption": "C",
        "context": "Ctx",
        "row_count": 1,
        "column_count": 1,
    }

    with (
        patch("orchestration.activities._psycopg", return_value=psycopg),
        patch("orchestration.activities.get_full_table", return_value=fake_table),
    ):
        reference = asyncio.run(
            workflow_activities.execute_tool_activity(
                "session-1", "get_full_table", {"doc_id": "doc-1", "table_id": "table-1"}
            )
        )

    assert reference["tool_name"] == "get_full_table"
    assert reference["tool_result_id"]


def test_execute_tool_activity_persists_only_a_compact_calculator_reference() -> None:
    """A registry-selected secondary MCP tool stores raw output outside workflow state."""
    cursor = MagicMock()
    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    psycopg = MagicMock()
    psycopg.connect.return_value.__enter__.return_value = connection
    tool = {
        "spec": {
            "name": "calculator",
            "description": "Evaluate a mathematical expression.",
            "parameters": {
                "type": "object",
                "properties": {"expression": {"type": "string"}},
                "required": ["expression"],
                "additionalProperties": False,
            },
            "timeout_seconds": 10,
        },
        "command": "calculator-mcp",
        "args": ["--stdio"],
        "env": {"CALCULATOR_TOKEN": "local-token"},
    }

    with (
        patch("orchestration.activities._psycopg", return_value=psycopg),
        patch("orchestration.activities.resolve_mcp_tool", return_value=tool),
        patch(
            "orchestration.activities.call_mcp_tool",
            new=AsyncMock(return_value={"content": [{"text": "4"}]}),
        ) as call,
    ):
        reference = asyncio.run(
            execute_tool_activity("session-1", "calculator", {"expression": "2 + 2"})
        )

    assert reference["tool_name"] == "calculator"
    assert reference["tool_result_id"]
    call.assert_awaited_once_with(
        "calculator-mcp",
        ["--stdio"],
        "calculator",
        {"expression": "2 + 2"},
        server_env={"CALCULATOR_TOKEN": "local-token"},
        timeout_seconds=10,
    )
    statement, parameters = cursor.execute.call_args.args
    assert "INSERT INTO agent_tool_results" in statement
    assert parameters[1:3] == ("session-1", "calculator")
    assert json.loads(parameters[3]) == {"content": [{"text": "4"}]}


def test_summarize_session_history_persists_constrained_gemini_summary() -> None:
    """The async activity stores only a concise, planning-safe conversation summary."""
    cursor = MagicMock()
    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    psycopg = MagicMock()
    psycopg.connect.return_value.__enter__.return_value = connection
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=(
                        "Topic: IFC financial statements. Entity: IFC. "
                        "Established answer: net income figures are requested by fiscal year."
                    )
                )
            )
        ]
    )
    messages = [
        {"role": "user", "content": "Compare IFC net income for 2024 and 2023."},
        {"role": "assistant", "content": "I will use the annual report."},
    ]

    with (
        patch("orchestration.activities._psycopg", return_value=psycopg),
        patch.object(
            workflow_activities.llm_client.chat.completions,
            "create",
            return_value=completion,
        ) as create,
    ):
        summary = summarize_session_history_activity("user-1", "session-1", messages)

    assert summary.startswith("Topic: IFC financial statements.")
    assert len(summary.split()) <= 180
    prompt = create.call_args.kwargs["messages"][0]["content"]
    assert "active user topic and named entities" in prompt
    assert "decisions already made" in prompt
    assert "Do not add facts" in prompt
    statement, params = cursor.execute.call_args.args
    assert "UPDATE user_sessions" in statement
    assert "conversation_summary = %s" in statement
    assert params == (summary, "user-1", "session-1")


def test_load_history_node_injects_summary_and_prunes_raw_turns() -> None:
    """Planning receives the durable summary plus only the most recent raw chat turns."""
    raw_messages = [
        {"role": "user" if index % 2 == 0 else "assistant", "content": f"turn {index}"}
        for index in range(8)
    ]

    result = load_history_node(
        {
            "messages": raw_messages,
            "history": [{"role": "system", "content": "Known user fact: IFC."}],
            "conversation_summary": "Topic: IFC net income. Constraint: use page citations.",
            "history_injected": False,
        }
    )

    assert result["history_injected"] is True
    assert result["messages"][0] == {
        "role": "system",
        "content": (
            "Conversation summary for planning:\n"
            "Topic: IFC net income. Constraint: use page citations."
        ),
    }
    assert result["messages"][1]["content"] == "Known user fact: IFC."
    assert [message["content"] for message in result["messages"][2:]] == [
        "turn 2",
        "turn 3",
        "turn 4",
        "turn 5",
        "turn 6",
        "turn 7",
    ]


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


@activity.defn(name="summarize_session_history_activity")
def _summarize_session_history(
    _user_id: str,
    _session_id: str,
    _messages: list[dict[str, Any]],
) -> str:
    """Provide a non-blocking stand-in for the Gemini history compressor."""
    CALLS["session_summary"] += 1
    return "Active topic: deterministic workflow testing."


def _next_action(state: dict[str, Any]) -> dict[str, Any]:
    """Model the agent's persisted plan without invoking Gemini in workflow tests."""
    result = dict(state)
    if "agent_plan" not in result:
        if result["query"] == "direct conversation":
            tool_sequence: list[str] = []
            intent = "conversation"
            document_only = False
        elif result["query"] == "ambiguous with web":
            tool_sequence = ["hybrid_search", "tavily_search"]
            intent = "document_and_web"
            document_only = False
        elif result["query"] == "calculator":
            tool_sequence = ["calculator"]
            intent = "document_and_web"
            document_only = False
        elif result["query"] == "inspect table":
            tool_sequence = ["get_full_table"]
            intent = "document"
            document_only = True
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
            "tool_arguments": (
                {"calculator": {"expression": "2 + 2"}}
                if result["query"] == "calculator"
                else {"get_full_table": {"doc_id": "document-1", "table_id": "table-1"}}
                if result["query"] == "inspect table"
                else {}
            ),
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
        result["next_action"] = (
            "hybrid_search"
            if remaining and remaining[0] == "hybrid_search"
            else "mcp_search" if remaining else "ask_clarification"
        )
    elif remaining := [
        tool for tool in plan["tool_sequence"] if tool not in completed_tools
    ]:
        result["next_action"] = (
            "hybrid_search" if remaining[0] == "hybrid_search" else "mcp_search"
        )
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


@activity.defn(name="execute_tool_activity")
async def _mcp(
    _session_id: str, tool_name: str, _arguments: dict[str, Any]
) -> dict[str, str]:
    """Return a compact persisted-MCP reference."""
    CALLS["mcp"] += 1
    return {"tool_result_id": "tool-1", "tool_name": tool_name}


@activity.defn(name="execute_tool_activity")
async def _flaky_mcp(
    _session_id: str, tool_name: str, _arguments: dict[str, Any]
) -> dict[str, str]:
    """Fail once to prove only the MCP activity, not retrieval, is retried."""
    CALLS["mcp"] += 1
    if CALLS["mcp"] == 1:
        raise ApplicationError("temporary MCP outage", type="McpToolError")
    return {"tool_result_id": "tool-1", "tool_name": tool_name}


@activity.defn(name="get_full_table_activity")
def _get_full_table_mock(
    _session_id: str,
    _doc_id: str,
    _table_id: str,
    _allowed_document_ids: list[str],
) -> dict[str, str]:
    """Provide a deterministic full table result double."""
    CALLS["get_full_table"] += 1
    return {"tool_result_id": "table-result-1", "tool_name": "get_full_table"}


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
    messages: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Run the workflow with isolated activity doubles and optional HITL signals."""
    CALLS.clear()
    task_queue = f"orchestration-resilience-{uuid4()}"
    activities = [
        _history,
        _decision_graph,
        _retrieval,
        _verify,
        _get_full_table_mock,
        mcp_activity,
        _answer,
        _direct_answer,
        _persist_session,
        _summarize_session_history,
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
                    args=[query, "integration-test-user", None, messages],
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


@activity.defn(name="count_reindexable_children_activity")
def _count_reindexable_children() -> int:
    """Return the stable total used by the batch-reindex status query."""
    CALLS["reindex_count"] += 1
    return 3


@activity.defn(name="fetch_unindexed_chunk_batch_activity")
def _fetch_reindex_batch(
    batch_size: int, cursor_id: str | None
) -> list[dict[str, str]]:
    """Yield deterministic pages of child rows from a stable cursor."""
    CALLS["reindex_fetch"] += 1
    assert batch_size == 2
    batches = {
        None: [
            {"id": "child-1", "retrieval_text": "first"},
            {"id": "child-2", "retrieval_text": "second"},
        ],
        "child-2": [{"id": "child-3", "retrieval_text": "third"}],
        "child-3": [],
    }
    return batches[cursor_id]


@activity.defn(name="reindex_chunk_batch_activity")
def _reindex_batch_after_network_drop(chunks: list[dict[str, str]]) -> str:
    """Fail one batch once, then prove Temporal retries only that atomic unit."""
    CALLS["reindex_batch"] += 1
    chunk_ids = [chunk["id"] for chunk in chunks]
    if chunk_ids == ["child-1", "child-2"] and CALLS["reindex_batch"] == 1:
        raise ApplicationError("temporary embedding network failure", type="NetworkError")
    COMMITTED_REINDEX_IDS.extend(chunk_ids)
    return chunk_ids[-1]


async def _run_batch_reindex_workflow() -> dict[str, Any]:
    """Execute the reindex workflow against local retry-aware activity doubles."""
    CALLS.clear()
    COMMITTED_REINDEX_IDS.clear()
    task_queue = f"batch-reindex-{uuid4()}"
    activities = [
        _count_reindexable_children,
        _fetch_reindex_batch,
        _reindex_batch_after_network_drop,
    ]
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        with ThreadPoolExecutor(max_workers=2) as executor:
            async with Worker(
                environment.client,
                task_queue=task_queue,
                workflows=[BatchReindexWorkflow],
                activities=activities,
                activity_executor=executor,
            ):
                handle = await environment.client.start_workflow(
                    BatchReindexWorkflow.run,
                    args=[2],
                    id=f"reindex-{uuid4()}",
                    task_queue=task_queue,
                )
                return await handle.result()


def test_batch_reindex_workflow_retries_only_failed_batch_without_duplicate_updates() -> None:
    """Network retries preserve the cursor and commit every child ID exactly once."""
    result = asyncio.run(_run_batch_reindex_workflow())

    assert result == {
        "status": "completed",
        "processed_count": 3,
        "total_count": 3,
        "last_processed_id": "child-3",
        "error": None,
    }
    assert CALLS["reindex_batch"] == 3
    assert COMMITTED_REINDEX_IDS == ["child-1", "child-2", "child-3"]


def test_workflow_executes_get_full_table_tool() -> None:
    """The workflow dispatches get_full_table_activity and retains its result reference."""
    _, result = asyncio.run(_run_fake_workflow("inspect table"))

    assert result["status"] == "completed"
    assert result["evidence"] == [
        {"tool_result_id": "table-result-1", "tool_name": "get_full_table"}
    ]
    assert "mcp_tool_started:get_full_table" in result["execution_history"]
    assert CALLS["get_full_table"] == 1


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
        get_full_table_activity,
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


def test_registry_selected_calculator_runs_through_generic_tool_activity() -> None:
    """The workflow executes a non-Tavily MCP tool and keeps only its persisted ID."""
    _, result = asyncio.run(_run_fake_workflow("calculator"))

    assert result["status"] == "completed"
    assert result["evidence"] == [{"tool_result_id": "tool-1", "tool_name": "calculator"}]
    assert result["sources_used"] == ["mcp_tools"]
    assert CALLS["mcp"] == 1


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


def test_multi_turn_workflow_starts_summary_without_delaying_final_response() -> None:
    """Six or more turns schedule durable compression after the chat response is ready."""
    messages = [
        {
            "role": "user" if index % 2 == 0 else "assistant",
            "content": f"conversation turn {index}",
        }
        for index in range(6)
    ]

    _, result = asyncio.run(
        _run_fake_workflow("direct conversation", messages=messages)
    )

    assert result["status"] == "completed"
    assert result["final_answer"] == "Conversational answer"
    assert "session_persisted" in result["execution_history"]
    assert "session_history_summarization_started" in result["execution_history"]


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
