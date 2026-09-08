"""Build and render the bounded, side-effect-free LangGraph ReAct DAG."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from agent.nodes import (
    ask_clarification_node,
    direct_answer_node,
    hybrid_search_node,
    load_history_node,
    mcp_search_node,
    planner_node,
    synthesize_answer_node,
    verify_groundedness_node,
)
from agent.state import AgentState

Route = Literal[
    "hybrid_search",
    "verify_groundedness",
    "mcp_search",
    "ask_clarification",
    "direct_answer",
    "generate_answer",
]


def _route_from_planner(state: AgentState) -> Route:
    """Return the planner-selected action for one Temporal activity invocation."""
    return state["next_action"]


_COMPILED_AGENT: Any | None = None


def compile_agent_graph() -> Any:
    """Compile a pure decision graph with no database or network access."""
    builder = StateGraph(AgentState)
    builder.add_node("load_history", load_history_node)
    builder.add_node("planner", planner_node)
    builder.add_node("hybrid_search", hybrid_search_node)
    builder.add_node("verify_groundedness", verify_groundedness_node)
    builder.add_node("mcp_search", mcp_search_node)
    builder.add_node("ask_clarification", ask_clarification_node)
    builder.add_node("direct_answer", direct_answer_node)
    builder.add_node("synthesize_answer", synthesize_answer_node)
    builder.add_edge(START, "load_history")
    builder.add_edge("load_history", "planner")
    builder.add_conditional_edges(
        "planner",
        _route_from_planner,
        {
            "hybrid_search": "hybrid_search",
            "verify_groundedness": "verify_groundedness",
            "mcp_search": "mcp_search",
            "ask_clarification": "ask_clarification",
            "direct_answer": "direct_answer",
            "generate_answer": "synthesize_answer",
        },
    )
    builder.add_edge("hybrid_search", END)
    builder.add_edge("verify_groundedness", "planner")
    builder.add_edge("mcp_search", END)
    builder.add_edge("ask_clarification", END)
    builder.add_edge("direct_answer", END)
    builder.add_edge("synthesize_answer", END)
    return builder.compile()


def get_agent() -> Any:
    """Return the process-local compiled agent used by Temporal think activities."""
    global _COMPILED_AGENT
    if _COMPILED_AGENT is None:
        _COMPILED_AGENT = compile_agent_graph()
    return _COMPILED_AGENT


def render_graph_png(output_path: str | Path | None = None) -> bytes:
    """Render the compiled ReAct DAG and optionally write it to a PNG file."""
    png = compile_agent_graph().get_graph().draw_mermaid_png()
    if output_path is not None:
        Path(output_path).write_bytes(png)
    return png
