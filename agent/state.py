"""Primitive, bounded state passed between LangGraph decision nodes."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field

AgentTool = Literal["hybrid_search", "mcp_search"]
AgentIntent = Literal["conversation", "document", "web", "document_and_web", "clarify"]
DocumentLookupMode = Literal["semantic", "overview"]


class AgentPlan(BaseModel):
    """Structured Gemini decision for one conversational agent turn."""

    intent: AgentIntent
    tool_sequence: list[AgentTool] = Field(default_factory=list, max_length=2)
    document_only: bool = False
    document_lookup: DocumentLookupMode = "semantic"
    document_query: str = Field(default="", max_length=1000)
    web_query: str = Field(default="", max_length=1000)
    clarification_question: str = Field(default="", max_length=500)
    reason: str = Field(min_length=1, max_length=500)


class AgentState(TypedDict, total=False):
    """Serializable state for one agent turn without embedded source payloads."""

    query: str
    user_id: str
    session_id: str
    messages: list[dict[str, str]]
    history: list[dict[str, str]]
    document_ids: list[str]
    attached_documents: list[dict[str, str]]
    retrieved_evidence: list[dict[str, Any]]
    mcp_results: list[dict[str, Any]]
    retrieval_response: dict[str, Any]
    agent_plan: dict[str, Any]
    completed_tools: list[AgentTool]
    tool_errors: dict[str, str]
    clarification_needed: bool
    context_sufficient: bool
    user_choice: str
    final_answer: str
    iteration_count: int
    max_turns: int
    verification_pending: bool
    history_injected: bool
    next_action: Literal[
        "hybrid_search",
        "verify_groundedness",
        "mcp_search",
        "ask_clarification",
        "direct_answer",
        "generate_answer",
    ]
