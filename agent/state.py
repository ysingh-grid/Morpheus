"""Primitive, bounded state passed between LangGraph decision nodes."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field

AgentIntent = Literal["conversation", "document", "web", "document_and_web", "clarify"]
DocumentLookupMode = Literal["semantic", "overview", "table", "figure", "page"]

MAX_RETRIEVAL_SHOTS = 3
MAX_TOOL_OBSERVATIONS = 8


def normalize_retrieval_query(query: str) -> str:
    """Collapse whitespace and case so identical retrieval queries can be detected."""
    return " ".join(query.casefold().split())


def retrieval_attempt_count(observations: list[dict[str, Any]] | None) -> int:
    """Count hybrid-search observations already recorded for this workflow."""
    return sum(1 for item in observations or [] if item.get("tool") == "hybrid_search")


def used_retrieval_queries(observations: list[dict[str, Any]] | None) -> set[str]:
    """Return normalized document queries that have already been executed."""
    return {
        normalize_retrieval_query(str(item.get("document_query", "")))
        for item in observations or []
        if item.get("tool") == "hybrid_search" and str(item.get("document_query", "")).strip()
    }


def hybrid_search_allowed(state: dict[str, Any], document_query: str) -> bool:
    """Allow hybrid search on a new query, including multi-shot retries after observations."""
    observations = list(state.get("tool_observations") or [])
    completed_tools = set(state.get("completed_tools") or [])
    normalized = normalize_retrieval_query(document_query)
    if not normalized:
        return False
    if retrieval_attempt_count(observations) >= MAX_RETRIEVAL_SHOTS:
        return False
    if normalized in used_retrieval_queries(observations):
        return False
    if not observations and "hybrid_search" in completed_tools:
        return False
    return True


def merge_retrieved_evidence(
    existing: list[dict[str, Any]] | None,
    incoming: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Union compact evidence references across retrieval shots without duplicates."""
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in [*(existing or []), *(incoming or [])]:
        chunk_id = str(item.get("chunk_id") or "")
        key = chunk_id or json_stable_evidence_key(item)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def json_stable_evidence_key(item: dict[str, Any]) -> str:
    """Fallback identity for evidence rows that do not yet have a chunk id."""
    return str(item.get("parent_id") or item.get("tool_result_id") or repr(sorted(item.items())))


def compact_retrieval_observation(
    *,
    document_query: str,
    document_lookup: str,
    retrieval: dict[str, Any],
    context_sufficient: bool | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Build a Temporal-safe observation for one hybrid-search activity."""
    evidence = list(retrieval.get("evidence") or [])
    confidence = dict(retrieval.get("confidence") or {})
    observation: dict[str, Any] = {
        "tool": "hybrid_search",
        "status": "error" if error else retrieval.get("status", "unknown"),
        "document_query": document_query[:1000],
        "document_lookup": document_lookup,
        "evidence_count": len(evidence),
        "chunk_ids": [
            chunk_id
            for chunk_id in (item.get("chunk_id") for item in evidence[:5])
            if isinstance(chunk_id, str) and chunk_id
        ],
        "confidence": {
            key: confidence[key]
            for key in (
                "rrf_score",
                "vector_distance",
                "lexical_match",
                "rrf_score_margin",
            )
            if key in confidence
        },
    }
    if context_sufficient is not None:
        observation["context_sufficient"] = bool(context_sufficient)
    if error:
        observation["error"] = error[:300]
    return observation


def compact_mcp_observation(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Build a Temporal-safe observation for one MCP or native tool activity."""
    observation: dict[str, Any] = {
        "tool": tool_name,
        "status": "error" if error else "ok",
        "arguments": arguments,
    }
    if result and result.get("tool_result_id"):
        observation["tool_result_id"] = result["tool_result_id"]
    if error:
        observation["error"] = error[:300]
    return observation


def append_tool_observation(
    observations: list[dict[str, Any]] | None,
    observation: dict[str, Any],
) -> list[dict[str, Any]]:
    """Append one observation and keep workflow state bounded."""
    return [*(observations or []), observation][-MAX_TOOL_OBSERVATIONS:]


class ToolSpec(TypedDict):
    """Public planning contract for one registry-backed MCP tool."""

    name: str
    description: str
    parameters: dict[str, Any]
    timeout_seconds: int


class AgentPlan(BaseModel):
    """Structured Gemini decision for one conversational agent turn."""

    intent: AgentIntent
    tool_sequence: list[str] = Field(default_factory=list, max_length=5)
    tool_arguments: dict[str, dict[str, Any]] = Field(default_factory=dict)
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
    conversation_summary: str
    document_ids: list[str]
    attached_documents: list[dict[str, str]]
    retrieved_evidence: list[dict[str, Any]]
    mcp_results: list[dict[str, Any]]
    retrieval_response: dict[str, Any]
    tool_observations: list[dict[str, Any]]
    agent_plan: dict[str, Any]
    completed_tools: list[str]
    tool_errors: dict[str, str]
    needs_replan: bool
    clarification_needed: bool
    context_sufficient: bool
    user_choice: str
    final_answer: str
    iteration_count: int
    max_turns: int
    verification_pending: bool
    history_injected: bool
    llm_model: str
    next_action: Literal[
        "hybrid_search",
        "verify_groundedness",
        "mcp_search",
        "ask_clarification",
        "direct_answer",
        "generate_answer",
    ]
