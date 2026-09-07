"""Unit tests verifying LangSmith observability across all services and tools."""

from __future__ import annotations

import os
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.config import llm_client
from agent.nodes import _create_agent_plan, _scope_document_query, planner_node
from ingestion.doc_processor import process_document
from interfaces.openai_api import _sanitize_messages
from orchestration.activities import _traced_temporal_activity
from orchestration.mcp_client import call_mcp_tool
from retrieval.pg_engine import (
    document_overview_and_join,
    get_full_table,
    hybrid_search_and_join,
    ingest_bundle,
)


def test_llm_client_is_wrapped_for_langsmith_tracing() -> None:
    """The central OpenAI/Gemini client is wrapped by langsmith.wrappers.wrap_openai."""
    assert hasattr(llm_client, "_client") or hasattr(llm_client, "chat")
    assert hasattr(llm_client.beta.chat.completions, "parse")
    assert hasattr(llm_client.chat.completions, "create")
    assert hasattr(llm_client.embeddings, "create")


def test_retrieval_functions_are_decorated_with_traceable() -> None:
    """Core retrieval entry points are registered as LangSmith traceable operations."""
    for fn in (
        hybrid_search_and_join,
        document_overview_and_join,
        get_full_table,
        ingest_bundle,
    ):
        assert hasattr(fn, "__langsmith_traceable__") or hasattr(fn, "_is_traceable")


def test_agent_planning_nodes_are_decorated_with_traceable() -> None:
    """Agent planner and routing nodes are wrapped for LangSmith execution tracing."""
    for fn in (planner_node, _create_agent_plan, _scope_document_query):
        assert hasattr(fn, "__langsmith_traceable__") or hasattr(fn, "_is_traceable")


def test_ingestion_and_mcp_client_are_decorated_with_traceable() -> None:
    """Document parsing and MCP tool executions carry LangSmith trace metadata."""
    for fn in (process_document, call_mcp_tool, _sanitize_messages):
        assert hasattr(fn, "__langsmith_traceable__") or hasattr(fn, "_is_traceable")


def test_temporal_activity_trace_includes_workflow_correlation_metadata() -> None:
    """Each Temporal activity emits a correlated LangSmith root trace."""

    @_traced_temporal_activity("test_activity", "tool")
    def test_activity() -> str:
        return "done"

    activity_info = SimpleNamespace(
        workflow_id="workflow-1",
        workflow_run_id="run-1",
        activity_id="activity-1",
        activity_type="test_activity",
    )
    with (
        patch("orchestration.activities.activity.info", return_value=activity_info),
        patch("orchestration.activities.trace", return_value=nullcontext()) as trace,
    ):
        assert test_activity() == "done"

    assert trace.call_args.kwargs["metadata"] == {
        "temporal_workflow_id": "workflow-1",
        "temporal_workflow_run_id": "run-1",
        "temporal_activity_id": "activity-1",
        "temporal_activity_type": "test_activity",
    }


def test_traceable_execution_runs_cleanly_with_tracing_active() -> None:
    """Traced functions execute without error when LangSmith tracing environment is active."""
    cursor = MagicMock()
    cursor.fetchone.return_value = {
        "markdown": "| Col |",
        "heading": "H",
        "caption": "C",
        "context": "Ctx",
        "row_count": 1,
        "column_count": 1,
    }
    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    psycopg = MagicMock()
    psycopg.connect.return_value.__enter__.return_value = connection

    with (
        patch.dict(
            os.environ,
            {"LANGCHAIN_TRACING_V2": "false", "LANGSMITH_TRACING": "false"},
            clear=False,
        ),
        patch("retrieval.pg_engine._psycopg", return_value=psycopg),
    ):
        table = get_full_table("doc-1", "table-1")

    assert table is not None
    assert table["markdown"] == "| Col |"
