"""Unit coverage for LangGraph ReAct tool-routing decisions."""

from __future__ import annotations

from agent.graph import compile_agent_graph
from agent.nodes import _fallback_plan, _scope_document_query, planner_node, verify_groundedness_node
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
