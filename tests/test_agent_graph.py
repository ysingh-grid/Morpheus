"""Unit coverage for LangGraph ReAct tool-routing decisions."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent.graph import compile_agent_graph, get_agent
from agent.nodes import (
    _create_agent_plan,
    _fallback_plan,
    _scope_document_query,
    planner_node,
    verify_groundedness_node,
)
from agent.state import (
    AgentPlan,
    hybrid_search_allowed,
    merge_retrieved_evidence,
)


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


def test_gemini_selected_registered_calculator_is_preserved_with_arguments() -> None:
    """Planner accepts registry-backed tools instead of a fixed MCP tool literal."""
    selected_plan = AgentPlan(
        intent="web",
        tool_sequence=["calculator"],
        tool_arguments={"calculator": {"expression": "2 + 2"}},
        reason="A calculator tool can evaluate the requested expression.",
    )
    completion = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(parsed=selected_plan))]
    )

    with patch(
        "agent.nodes.llm_client.beta.chat.completions.parse", return_value=completion
    ):
        plan = _create_agent_plan(
            {"query": "Calculate 2 + 2", "document_ids": [], "messages": []}
        )

    assert plan.tool_sequence == ["calculator"]
    assert plan.tool_arguments == {"calculator": {"expression": "2 + 2"}}


def test_gemini_selected_get_full_table_is_preserved_with_arguments() -> None:
    """Planner accepts native get_full_table tool with doc_id and table_id."""
    selected_plan = AgentPlan(
        intent="document",
        tool_sequence=["get_full_table"],
        tool_arguments={"get_full_table": {"doc_id": "doc-1", "table_id": "table-1"}},
        reason="Inspect the complete balance sheet table.",
    )
    completion = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(parsed=selected_plan))]
    )

    with patch(
        "agent.nodes.llm_client.beta.chat.completions.parse", return_value=completion
    ):
        plan = _create_agent_plan(
            {"query": "Show me full table 1", "document_ids": ["doc-1"], "messages": []}
        )

    assert plan.tool_sequence == ["get_full_table"]
    assert plan.tool_arguments == {
        "get_full_table": {"doc_id": "doc-1", "table_id": "table-1"}
    }


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


def test_get_agent_reuses_the_process_local_compiled_graph() -> None:
    """Temporal think activities must wrap one compiled agent, not rebuild it."""
    assert get_agent() is get_agent()


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
            "tool_sequence": ["tavily_search"],
            "document_only": False,
            "clarification_question": "",
            "reason": "The user explicitly requested web search.",
        },
    }

    assert planner_node(state) == {"next_action": "mcp_search"}
    state["mcp_results"] = [{"tool_result_id": "tool-1", "tool_name": "tavily_search"}]
    state["completed_tools"] = ["tavily_search"]
    assert planner_node(state) == {"next_action": "generate_answer"}


def test_planner_node_runs_document_and_web_tools_in_sequence() -> None:
    """One turn may use both session documents and web evidence before synthesis."""
    state = {
        "query": "Compare this report with current web information.",
        "agent_plan": {
            "intent": "document_and_web",
            "tool_sequence": ["hybrid_search", "tavily_search"],
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


def test_planner_answers_from_documents_after_web_search_is_declined() -> None:
    """A cancelled Tavily gate must not re-enter HITL; it should synthesize locally."""
    result = planner_node(
        {
            "query": "What were IFC's assets?",
            "user_choice": "cancel",
            "needs_replan": False,
            "clarification_needed": True,
            "retrieved_evidence": [{"chunk_id": "chunk-1"}],
            "mcp_results": [],
            "completed_tools": ["hybrid_search", "tavily_search"],
            "agent_plan": {
                "intent": "document_and_web",
                "tool_sequence": ["hybrid_search", "tavily_search"],
                "document_only": False,
                "clarification_question": "",
                "reason": "Web search was requested, then declined.",
            },
        }
    )

    assert result == {"next_action": "generate_answer"}


def test_planner_replans_from_tool_observations_instead_of_walking_the_old_sequence() -> None:
    """A new observation must invoke Gemini again rather than reusing the first plan."""
    selected_plan = AgentPlan(
        intent="document",
        tool_sequence=["hybrid_search"],
        document_only=True,
        document_query="IFC consolidated total assets 30 June 2024",
        document_lookup="table",
        reason="The first search missed the balance-sheet wording.",
    )
    completion = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(parsed=selected_plan))]
    )
    state = {
        "query": "What were IFC's assets?",
        "document_ids": ["ifc-report"],
        "needs_replan": True,
        "agent_plan": {
            "intent": "document",
            "tool_sequence": ["hybrid_search"],
            "document_only": True,
            "document_query": "What were IFC's assets?",
            "reason": "Initial plan.",
        },
        "completed_tools": ["hybrid_search"],
        "tool_observations": [
            {
                "tool": "hybrid_search",
                "status": "not_found",
                "document_query": "What were IFC's assets?",
                "document_lookup": "semantic",
                "evidence_count": 0,
                "chunk_ids": [],
                "confidence": {},
            }
        ],
        "retrieved_evidence": [],
        "messages": [],
    }

    with patch(
        "agent.nodes.llm_client.beta.chat.completions.parse", return_value=completion
    ) as parsed:
        result = planner_node(state)

    parsed.assert_called_once()
    assert result["needs_replan"] is False
    assert result["next_action"] == "hybrid_search"
    assert result["agent_plan"]["document_query"] == (
        "IFC consolidated total assets 30 June 2024"
    )


def test_planner_rejects_identical_retrieval_query_after_an_observation() -> None:
    """Multi-shot retrieval cannot loop on the same document query."""
    result = planner_node(
        {
            "query": "What were IFC's assets?",
            "document_ids": ["ifc-report"],
            "agent_plan": {
                "intent": "document",
                "tool_sequence": ["hybrid_search"],
                "document_only": True,
                "document_query": "What were IFC's assets?",
                "reason": "Repeat the same search.",
            },
            "completed_tools": ["hybrid_search"],
            "tool_observations": [
                {
                    "tool": "hybrid_search",
                    "status": "not_found",
                    "document_query": "What were IFC's assets?",
                    "evidence_count": 0,
                    "chunk_ids": [],
                }
            ],
            "retrieved_evidence": [],
        }
    )

    assert result == {"next_action": "ask_clarification"}


def test_hybrid_search_allowed_permits_rewritten_query_and_blocks_duplicates() -> None:
    """A later shot is allowed only when the retrieval query actually changed."""
    state = {
        "completed_tools": ["hybrid_search"],
        "tool_observations": [
            {
                "tool": "hybrid_search",
                "status": "not_found",
                "document_query": "What were IFC's assets?",
            }
        ],
    }
    assert hybrid_search_allowed(state, "What were IFC's assets?") is False
    assert hybrid_search_allowed(state, "IFC total assets 2024") is True


def test_merge_retrieved_evidence_keeps_unique_chunk_ids_across_shots() -> None:
    """Later retrieval shots accumulate new parents instead of replacing earlier hits."""
    merged = merge_retrieved_evidence(
        [{"chunk_id": "chunk-1", "parent_id": "parent-1"}],
        [
            {"chunk_id": "chunk-1", "parent_id": "parent-1"},
            {"chunk_id": "chunk-2", "parent_id": "parent-2"},
        ],
    )
    assert [item["chunk_id"] for item in merged] == ["chunk-1", "chunk-2"]


def test_create_agent_plan_sends_tool_observations_when_replanning() -> None:
    """Gemini must see compact tool outcomes before choosing the next action."""
    selected_plan = AgentPlan(
        intent="document",
        tool_sequence=[],
        reason="Observed evidence is sufficient.",
    )
    completion = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(parsed=selected_plan))]
    )
    observations = [
        {
            "tool": "hybrid_search",
            "status": "grounded",
            "document_query": "IFC assets 2024",
            "evidence_count": 1,
            "chunk_ids": ["chunk-1"],
        }
    ]

    with patch(
        "agent.nodes.llm_client.beta.chat.completions.parse", return_value=completion
    ) as parsed:
        plan = _create_agent_plan(
            {
                "query": "What were IFC's assets?",
                "document_ids": ["ifc-report"],
                "messages": [],
                "tool_observations": observations,
                "retrieved_evidence": [{"chunk_id": "chunk-1"}],
            }
        )

    payload = json.loads(parsed.call_args.kwargs["messages"][1]["content"])
    assert payload["tool_observations"] == observations
    assert payload["retrieval_attempt_count"] == 1
    assert payload["remaining_retrieval_shots"] == 2
    assert plan.tool_sequence == []
