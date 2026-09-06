"""Unit coverage for LangGraph ReAct tool-routing decisions."""

from __future__ import annotations

import pytest

from agent.graph import compile_agent_graph
from agent.nodes import (
    _create_agent_plan,
    _fallback_plan,
    _scope_document_query,
    planner_node,
    verify_groundedness_node,
)
from agent.state import AgentPlan


def test_planner_node_document_plan_selects_hybrid_search() -> None:
    """The agent retrieves only when its plan identifies relevant chat documents."""
    result = planner_node(
        {
            "query": "What were IFC's assets?",
            "document_ids": ["ifc-report"],
            "agent_plan": {
                "intent": "document",
                "tool_sequence": ["hybrid_search"],
                "document_only": True,
                "clarification_question": "",
                "reason": "The user asked about the uploaded report.",
            },
        }
    )
    assert result == {"next_action": "hybrid_search"}


def test_planner_node_conversation_plan_selects_direct_answer() -> None:
    """Ordinary conversation must not force document or web retrieval."""
    result = planner_node(
        {
            "query": "Hello, how are you?",
            "agent_plan": {
                "intent": "conversation",
                "tool_sequence": [],
                "document_only": False,
                "clarification_question": "",
                "reason": "No external context is needed.",
            },
        }
    )
    assert result == {"next_action": "direct_answer"}


@pytest.mark.parametrize(
    "query",
    [
        "Tabulate those figures.",
        "What was the change from 2023 to 2024?",
        "On which page did you find those figures?",
    ],
)
def test_follow_up_transform_uses_prior_answer_without_retrieval(query: str) -> None:
    """Formatting, arithmetic, and citation follow-ups reuse grounded chat output."""
    plan = _create_agent_plan(
        {
            "query": query,
            "document_ids": ["document-1"],
            "messages": [
                {"role": "user", "content": "What were the figures?"},
                {
                    "role": "assistant",
                    "content": "2024: 10; 2023: 8 [Source: report.pdf, p. 4].",
                },
                {"role": "user", "content": query},
            ],
        }
    )

    assert plan.intent == "conversation"
    assert plan.tool_sequence == []


def test_fallback_plan_requests_attachment_for_missing_document_context() -> None:
    """A document-specific request must not search unrelated globally stored documents."""
    plan = _fallback_plan(
        {
            "query": "What does this PDF say?",
            "document_ids": [],
        }
    )

    assert plan.intent == "clarify"
    assert plan.tool_sequence == []
    assert "attach" in plan.clarification_question.casefold()


def test_document_overview_query_uses_attached_document_profile() -> None:
    """A generic title request must retrieve the opening content of the scoped document."""
    plan = AgentPlan(
        intent="document",
        tool_sequence=["hybrid_search"],
        document_only=True,
        document_query="What is the title?",
        reason="The user asks about the attached document.",
    )

    scoped = _scope_document_query(
        plan,
        {
            "query": "What is the title?",
            "attached_documents": [
                {
                    "id": "document-1",
                    "name": "Circular For 2026 Batch",
                    "summary": "Academic Award Ceremony Udaan-2026.",
                }
            ],
        },
    )

    assert scoped.document_lookup == "overview"
    assert "Circular For 2026 Batch" in scoped.document_query
    assert "Academic Award Ceremony" in scoped.document_query


@pytest.mark.parametrize(
    "query",
    [
        "more in depth about the topic above",
        "can you go deeper on that?",
        "what about the limitations?",
    ],
)
def test_short_document_follow_up_includes_previous_subject_for_retrieval(query: str) -> None:
    """Short follow-ups must search the prior topic rather than literal vague wording."""
    plan = AgentPlan(
        intent="document",
        tool_sequence=["hybrid_search"],
        document_only=True,
        document_query=query,
        reason="The user asks a follow-up about the attached report.",
    )

    scoped = _scope_document_query(
        plan,
        {
            "query": query,
            "history": [
                {
                    "role": "system",
                    "content": (
                        "Latest user query: What is the TL;DR of this report? "
                        "Latest assistant answer: The report covers TinyLlama instruction "
                        "tuning on Apple Silicon using MLX-LM."
                    ),
                }
            ],
            "messages": [
                {"role": "user", "content": query}
            ],
        },
    )

    assert scoped.document_query.startswith(query)
    assert "Conversation context:" in scoped.document_query
    assert "TinyLlama instruction tuning on Apple Silicon" in scoped.document_query


def test_document_query_without_prior_turn_does_not_invent_context() -> None:
    """A first-turn document question must not fabricate a prior conversational subject."""
    query = "what about the limitations?"
    plan = AgentPlan(
        intent="document",
        tool_sequence=["hybrid_search"],
        document_only=True,
        document_query=query,
        reason="The user asks about the attached report.",
    )

    scoped = _scope_document_query(plan, {"query": query, "messages": []})

    assert scoped.document_query == query


def test_document_query_excludes_unrelated_user_fact_from_retrieval_context() -> None:
    """Personal-memory system messages must not bias a document similarity search."""
    query = "tell me more"
    plan = AgentPlan(
        intent="document",
        tool_sequence=["hybrid_search"],
        document_only=True,
        document_query=query,
        reason="The user asks a follow-up about the attached report.",
    )

    scoped = _scope_document_query(
        plan,
        {
            "query": query,
            "history": [
                {"role": "system", "content": "Known user fact: favorite color = blue"},
                {
                    "role": "system",
                    "content": "Latest assistant answer: TinyLlama uses MLX-LM on Apple Silicon.",
                },
            ],
            "messages": [{"role": "user", "content": query}],
        },
    )

    assert "TinyLlama uses MLX-LM" in scoped.document_query
    assert "favorite color" not in scoped.document_query


def test_verify_groundedness_node_requests_clarification_for_weak_retrieval() -> None:
    """Non-grounded confidence must become an explicit HITL state."""
    result = verify_groundedness_node(
        {
            "retrieval_response": {
                "status": "clarification_needed",
                "confidence": {"reasons": ["RRF score margin is too small."]},
            }
        }
    )
    assert result == {"clarification_needed": True, "verification_pending": False}


def test_compile_agent_graph_exposes_the_react_dag() -> None:
    """The graph must compile with the requested planner and tool nodes."""
    graph = compile_agent_graph()
    node_names = set(graph.get_graph().nodes)
    assert {
        "load_history",
        "planner",
        "hybrid_search",
        "verify_groundedness",
        "mcp_search",
        "ask_clarification",
        "direct_answer",
        "synthesize_answer",
    } <= node_names


def test_planner_node_at_turn_limit_routes_to_safe_clarification() -> None:
    """A bounded agent must not select another tool after its maximum turns."""
    result = planner_node(
        {
            "iteration_count": 5,
            "max_turns": 5,
            "retrieval_response": {"status": "grounded"},
        }
    )
    assert result == {"next_action": "ask_clarification"}


def test_planner_node_routes_explicit_web_request_to_mcp_after_local_retrieval() -> None:
    """Direct web-search authorization must not be blocked by document retrieval status."""
    state = {
        "query": "Go on the web and find more about EPFO",
        "retrieval_response": {"status": "not_found"},
        "mcp_results": [],
        "completed_tools": [],
        "agent_plan": {
            "intent": "web",
            "tool_sequence": ["mcp_search"],
            "document_only": False,
            "clarification_question": "",
            "reason": "The user explicitly requested web search.",
        },
    }

    assert planner_node(state) == {"next_action": "mcp_search"}
    state["mcp_results"] = [{"tool_result_id": "tool-1", "tool_name": "tavily_search"}]
    state["completed_tools"] = ["mcp_search"]
    assert planner_node(state) == {"next_action": "generate_answer"}


def test_planner_node_runs_document_and_web_tools_in_sequence() -> None:
    """One turn may use both session documents and web evidence before synthesis."""
    state = {
        "query": "Compare this report with current web information.",
        "agent_plan": {
            "intent": "document_and_web",
            "tool_sequence": ["hybrid_search", "mcp_search"],
            "document_only": False,
            "clarification_question": "",
            "reason": "Both sources are required.",
        },
        "completed_tools": [],
    }
    assert planner_node(state) == {"next_action": "hybrid_search"}
    state["completed_tools"] = ["hybrid_search"]
    state["retrieved_evidence"] = [{"chunk_id": "child-1"}]
    assert planner_node(state) == {"next_action": "mcp_search"}
