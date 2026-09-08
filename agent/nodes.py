"""LangGraph planning and routing nodes for the conversational agent."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from langsmith import traceable
from openai import APIError

from agent.state import (
    MAX_RETRIEVAL_SHOTS,
    AgentPlan,
    AgentState,
    hybrid_search_allowed,
    retrieval_attempt_count,
)
from core.config import DEFAULT_MODEL, llm_client
from orchestration.mcp_client import default_web_search_tool, registered_tool_specs

logger = logging.getLogger(__name__)


def _explicit_web_search_requested(query: str) -> bool:
    """Recognize direct user authorization to search beyond uploaded documents."""
    normalized = " ".join(query.casefold().split())
    return any(
        phrase in normalized
        for phrase in (
            "search the web",
            "go on the web",
            "search online",
            "look online",
            "find online",
            "browse the web",
        )
    )


def _explicit_document_request(query: str) -> bool:
    """Recognize questions that explicitly constrain the answer to uploaded material."""
    normalized = " ".join(query.casefold().split())
    return any(
        phrase in normalized
        for phrase in (
            "uploaded document",
            "uploaded file",
            "attached document",
            "attached file",
            "this document",
            "this pdf",
            "the document",
            "the pdf",
            "according to the document",
            "according to the pdf",
            "only from the document",
            "only from the pdf",
        )
    )


def _document_overview_request(query: str) -> bool:
    """Recognize deictic requests that need a document's opening context."""
    normalized = " ".join(query.casefold().split())
    return any(
        phrase in normalized
        for phrase in (
            "what is this document about",
            "what is the document about",
            "what is this pdf about",
            "what is the title",
            "document title",
            "title of this document",
            "title of the document",
            "summarize this document",
            "summarise this document",
            "summarize the document",
            "summarise the document",
        )
    )


def _conversation_transform_request(state: AgentState) -> bool:
    """Recognize follow-ups answerable entirely from a prior assistant response."""
    query = " ".join(state.get("query", "").casefold().split())
    has_prior_answer = any(
        message.get("role") == "assistant" and str(message.get("content", "")).strip()
        for message in state.get("messages", [])[:-1]
    )
    if not has_prior_answer:
        return False
    return bool(
        re.search(
            r"^(?:tabulate\b|put (?:that|those|it) in (?:a )?table\b|"
            r"present (?:that|those|it) (?:in|as) (?:a )?(?:markdown )?table\b|"
            r"reformat\b|on which page\b|what page\b|where did you find (?:that|those|it)\b|"
            r"what (?:was|is) the (?:change|difference|variance|percentage change)\b)",
            query,
        )
    )


def _document_lookup_mode(query: str) -> str:
    """Infer a retrieval policy from explicit structural cues in the user query."""
    normalized = " ".join(query.casefold().split())
    if _document_overview_request(query):
        return "overview"
    if re.search(r"\bpage\s+\d+\b", normalized):
        return "page"
    if re.search(r"\b(?:figure|fig\.?|chart|diagram|graph)\s*\d*\b", normalized):
        return "figure"
    if any(
        phrase in normalized
        for phrase in (
            "table",
            "tabulate",
            "balance sheet",
            "statement of operations",
            "financial statement",
            "break down",
            "breakdown",
            "across 2024",
        )
    ):
        return "table"
    return "semantic"


def _sanitize_conversation_context(text: str) -> str:
    """Remove raw attachment tags, URL links, and boilerplate from prior turn text."""
    cleaned = re.sub(r"<attached_files>.*?</attached_files>", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    return " ".join(cleaned.split()).strip()


def _conversation_retrieval_context(state: AgentState, current_query: str) -> str:
    """Extract bounded prior-turn context for an otherwise underspecified search query."""
    normalized_query = current_query.casefold()
    is_structural_nav = bool(
        re.search(
            r"\b(?:last\s+page|final\s+page|first\s+page|page\s+\d+|figure\s+\d+|fig\.?\s*\d+|table\s+\d+)\b",
            normalized_query,
        )
    )
    if is_structural_nav and len(current_query.split()) > 3:
        return ""

    messages = [*state.get("history", []), *state.get("messages", [])]
    context_parts: list[str] = []
    seen: set[tuple[str, str]] = set()
    for message in reversed(messages):
        role = str(message.get("role", "context"))
        raw_content = str(message.get("content", ""))
        content = _sanitize_conversation_context(raw_content)
        if not content or content == current_query:
            continue
        if role == "system" and not content.startswith("Latest "):
            continue
        key = (role, content)
        if key in seen:
            continue
        seen.add(key)
        snippet = content[:200]
        context_parts.append(f"{role}: {snippet}")
        if len(context_parts) == 2:
            break
    return "\n".join(reversed(context_parts))[:400]


@traceable(name="scope_document_query", run_type="chain")
def _scope_document_query(plan: AgentPlan, state: AgentState) -> AgentPlan:
    """Expand underspecified document follow-ups before their hybrid retrieval pass."""
    documents = state.get("attached_documents", [])
    query = state.get("query", "").strip()
    if "hybrid_search" not in plan.tool_sequence:
        return plan
    base_query = plan.document_query.strip() or query
    query_parts = [base_query]
    if len(query.split()) <= 32:
        context = _conversation_retrieval_context(state, query)
        if context:
            query_parts.append(f"Conversation context:\n{context}")
    inferred_lookup = _document_lookup_mode(query)
    if inferred_lookup != "semantic":
        plan.document_lookup = inferred_lookup
    is_overview = plan.document_lookup == "overview"
    if is_overview and len(documents) == 1:
        document = documents[0]
        profile = " ".join(
            part.strip()
            for part in (document.get("name", ""), document.get("summary", ""))
            if part.strip()
        )
        if profile:
            query_parts.append(f"Attached document: {profile}")
        plan.document_lookup = "overview"
    plan.document_query = "\n\n".join(query_parts)[:1000]
    return plan


@traceable(name="fallback_plan", run_type="chain")
def _fallback_plan(state: AgentState) -> AgentPlan:
    """Return a conservative tool plan if Gemini planning is temporarily unavailable."""
    query = state.get("query", "")
    has_documents = bool(state.get("document_ids"))
    wants_web = _explicit_web_search_requested(query)
    explicit_document_request = _explicit_document_request(query)
    wants_documents = has_documents and explicit_document_request
    web_search_tool = default_web_search_tool()
    observations = list(state.get("tool_observations") or [])
    if observations:
        if state.get("retrieved_evidence") or state.get("mcp_results"):
            return AgentPlan(
                intent="document" if state.get("retrieved_evidence") else "web",
                tool_sequence=[],
                document_only=bool(state.get("retrieved_evidence"))
                and not bool(state.get("mcp_results")),
                reason="Fallback: answer from observed tool results after a planning failure.",
            )
        if has_documents and hybrid_search_allowed(state, query):
            return AgentPlan(
                intent="document",
                tool_sequence=["hybrid_search"],
                document_only=True,
                document_query=query,
                reason="Fallback: retry document retrieval after a planning failure.",
            )
        return AgentPlan(
            intent="clarify",
            tool_sequence=[],
            document_only=True,
            clarification_question="I could not find enough evidence. Please clarify your question.",
            reason="Fallback: no further safe tool remains after observed failures.",
        )
    if explicit_document_request and not has_documents and not wants_web:
        return AgentPlan(
            intent="clarify",
            tool_sequence=[],
            document_only=True,
            clarification_question="Please attach the document you want me to use in this chat.",
            reason="The request refers to a document, but this chat has no attached documents.",
        )
    if wants_web and wants_documents and web_search_tool:
        return AgentPlan(
            intent="document_and_web",
            tool_sequence=["hybrid_search", web_search_tool],
            document_only=False,
            document_query=query,
            web_query=query,
            tool_arguments={web_search_tool: {"query": query}},
            reason="Explicit document and web request detected by fallback routing.",
        )
    if wants_web and web_search_tool:
        return AgentPlan(
            intent="web",
            tool_sequence=[web_search_tool],
            web_query=query,
            tool_arguments={web_search_tool: {"query": query}},
            reason="Explicit web request detected by fallback routing.",
        )
    if wants_documents:
        return AgentPlan(
            intent="document",
            tool_sequence=["hybrid_search"],
            document_only=True,
            document_query=query,
            reason="Explicit uploaded-document request detected by fallback routing.",
        )
    return AgentPlan(
        intent="conversation",
        tool_sequence=[],
        reason="No explicit tool requirement detected by fallback routing.",
    )


@traceable(name="create_agent_plan", run_type="chain")
def _create_agent_plan(state: AgentState) -> AgentPlan:
    """Ask Gemini to choose zero, one, or multiple tools for the current turn."""
    observations = list(state.get("tool_observations") or [])
    if not observations and _conversation_transform_request(state):
        return AgentPlan(
            intent="conversation",
            tool_sequence=[],
            reason="The request transforms or calculates from the preceding answer.",
        )
    document_ids = state.get("document_ids", [])
    recent_messages = state.get("messages", [])[-12:]
    mcp_tools = registered_tool_specs()
    attempt_count = retrieval_attempt_count(observations)
    replan_instructions = (
        " You are replanning after tool_observations. Those records are compact outcomes, "
        "not full document text. If hybrid_search was not_found or clarification_needed and "
        f"remaining_retrieval_shots is greater than 0 (max {MAX_RETRIEVAL_SHOTS} shots), "
        "select hybrid_search again with a rewritten document_query and/or a different "
        "document_lookup. Never repeat an identical document_query. If retrieval is grounded "
        "or context_sufficient is true, prefer an empty tool_sequence and answer. "
        "If the user declined web search, never select tavily_search; answer from "
        "uploaded documents or conversation. This plan lists only the next tools to "
        "run now, typically zero or one."
        if observations
        else ""
    )
    completion = llm_client.beta.chat.completions.parse(
        model=DEFAULT_MODEL,
        response_format=AgentPlan,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are the central planner for a conversational assistant. Choose the "
                    "smallest sufficient sequence of tools for this turn. Use no tools for "
                    "ordinary conversation, writing, reasoning, or stable general knowledge. "
                    "Use hybrid_search when the user asks about an uploaded document or when "
                    "available document context is relevant to the ongoing conversation. Use "
                    "get_full_table to inspect full table markdown and context when a specific "
                    "table_id and doc_id are referenced or needed. Use "
                    "an MCP tool from available_mcp_tools for explicit web requests or information "
                    "that must be current or external computation. "
                    "Use both tools when the user asks to compare, verify, or enrich uploaded "
                    "content with web information. Set document_only=true only when the user "
                    "explicitly constrains the answer to an uploaded or attached document. "
                    "Set document_lookup=overview for title, summary, subject, or 'what is this "
                    "document about' questions; table for tabular or financial-statement facts; "
                    "figure for figures, charts, graphs, or diagrams; page for an explicit page "
                    "number; otherwise use semantic. "
                    "Choose clarify only when the request is genuinely ambiguous and cannot be "
                    "answered safely. Never select hybrid_search when no document IDs are "
                    "available. In this plan, list each tool at most once and in execution order. "
                    "You may select hybrid_search again in a later replan with a new query. "
                    "For every selected tool, write a concise standalone search query that "
                    "removes conversational routing phrases such as 'according to the uploaded "
                    "document' while preserving names, dates, numbers, and the information need. "
                    "For short document questions and follow-ups such as 'more detail' or 'the "
                    "topic above', resolve the subject from recent_conversation in document_query. "
                    "For each selected MCP tool, provide tool_arguments keyed by tool name and "
                    "conforming to that tool's JSON Schema."
                    + replan_instructions
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "current_query": state.get("query", ""),
                        "available_document_ids": document_ids,
                        "available_documents": state.get("attached_documents", []),
                        "available_mcp_tools": mcp_tools,
                        "recent_conversation": recent_messages,
                        "tool_observations": observations,
                        "retrieval_attempt_count": attempt_count,
                        "remaining_retrieval_shots": max(
                            0, MAX_RETRIEVAL_SHOTS - attempt_count
                        ),
                        "user_choice": state.get("user_choice") or "",
                        "has_retrieved_evidence": bool(state.get("retrieved_evidence")),
                        "has_mcp_results": bool(state.get("mcp_results")),
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    )
    plan = completion.choices[0].message.parsed
    if plan is None:
        raise ValueError("Gemini did not return a structured agent plan.")
    registered_tool_names = {tool["name"] for tool in mcp_tools}
    allowed_tools = {"hybrid_search", *registered_tool_names}
    unique_tools: list[str] = []
    for tool in plan.tool_sequence:
        if tool in allowed_tools and tool not in unique_tools:
            unique_tools.append(tool)
    if not document_ids:
        unique_tools = [tool for tool in unique_tools if tool != "hybrid_search"]
        if _explicit_document_request(state.get("query", "")) and not unique_tools:
            plan.intent = "clarify"
            plan.document_only = True
            plan.clarification_question = (
                "Please attach the document you want me to use in this chat."
            )
    plan.tool_sequence = unique_tools
    web_search_tool = default_web_search_tool()
    if state.get("user_choice") == "cancel" and web_search_tool:
        unique_tools = [tool for tool in unique_tools if tool != web_search_tool]
        plan.tool_sequence = unique_tools
        if plan.intent in {"web", "document_and_web"}:
            plan.intent = "document" if state.get("retrieved_evidence") else "conversation"
    if "hybrid_search" in unique_tools and not plan.document_query.strip():
        plan.document_query = state.get("query", "")
    plan.tool_arguments = {
        tool_name: arguments
        for tool_name, arguments in plan.tool_arguments.items()
        if tool_name in registered_tool_names and isinstance(arguments, dict)
    }
    for tool_name in unique_tools:
        if tool_name == "hybrid_search" or tool_name in plan.tool_arguments:
            continue
        if tool_name == default_web_search_tool():
            plan.tool_arguments[tool_name] = {
                "query": plan.web_query.strip() or state.get("query", "")
            }
    if default_web_search_tool() in unique_tools and not plan.web_query.strip():
        plan.web_query = state.get("query", "")
    if (
        _explicit_document_request(state.get("query", ""))
        and "hybrid_search" in unique_tools
        and not any(tool in registered_tool_names for tool in unique_tools)
    ):
        plan.document_only = True
    if plan.intent == "clarify" and not plan.clarification_question:
        plan.clarification_question = "Could you clarify what you would like me to help with?"
    return _scope_document_query(plan, state)


def _next_plan_action(state: AgentState, plan: dict[str, Any]) -> str | None:
    """Return the first currently executable tool from a fresh or residual plan."""
    completed_tools = set(state.get("completed_tools", []))
    registered_tool_names = {tool["name"] for tool in registered_tool_specs()}
    document_query = str(plan.get("document_query") or state.get("query") or "")
    for tool in plan.get("tool_sequence", []):
        if tool == "hybrid_search":
            if hybrid_search_allowed(state, document_query):
                return "hybrid_search"
            continue
        if tool in registered_tool_names and tool not in completed_tools:
            if tool == default_web_search_tool() and state.get("user_choice") == "cancel":
                continue
            return "mcp_search"
    return None


def _planned_action(state: AgentState, plan: dict[str, Any]) -> str:
    """Select the next tool or response action from the current plan and observations."""
    if state.get("verification_pending"):
        return "verify_groundedness"
    web_search_declined = state.get("user_choice") == "cancel"
    if plan.get("intent") == "clarify" and not web_search_declined:
        return "ask_clarification"

    next_tool = _next_plan_action(state, plan)
    web_search_tool = default_web_search_tool()
    completed_tools = set(state.get("completed_tools", []))
    has_tool_evidence = bool(state.get("retrieved_evidence") or state.get("mcp_results"))

    if state.get("clarification_needed") and not web_search_declined:
        if state.get("context_sufficient") and has_tool_evidence and not next_tool:
            return "generate_answer"
        if next_tool == "hybrid_search":
            return "hybrid_search"
        if next_tool == "mcp_search":
            return "mcp_search"
        if (
            state.get("user_choice") == "approve_web_search"
            and web_search_tool
            and web_search_tool not in completed_tools
        ):
            return "mcp_search"
        return "ask_clarification"

    if next_tool is not None:
        return next_tool
    if (
        state.get("user_choice") == "approve_web_search"
        and web_search_tool
        and web_search_tool not in completed_tools
    ):
        return "mcp_search"

    document_query = str(plan.get("document_query") or state.get("query") or "")
    if plan.get("document_only") and not has_tool_evidence:
        if hybrid_search_allowed(state, document_query):
            return "hybrid_search"
        return "ask_clarification"
    return "generate_answer" if has_tool_evidence else "direct_answer"


def load_history_node(state: AgentState) -> AgentState:
    """Inject history previously loaded by a dedicated Temporal activity."""
    if state.get("history_injected"):
        return {}
    conversation_summary = str(state.get("conversation_summary", "")).strip()
    summary_message = (
        [
            {
                "role": "system",
                "content": f"Conversation summary for planning:\n{conversation_summary}",
            }
        ]
        if conversation_summary
        else []
    )
    return {
        "messages": [
            *summary_message,
            *state.get("history", []),
            *state.get("messages", [])[-6:],
        ],
        "history_injected": True,
    }


@traceable(name="planner_node", run_type="chain")
def planner_node(state: AgentState) -> AgentState:
    """Plan once, then re-plan from tool observations after each Temporal activity."""
    if state.get("iteration_count", 0) >= state.get("max_turns", 5):
        return {"next_action": "ask_clarification"}
    if state.get("verification_pending"):
        return {"next_action": "verify_groundedness"}
    plan = state.get("agent_plan")
    if plan is None or state.get("needs_replan"):
        try:
            plan = _create_agent_plan(state).model_dump(mode="json")
        except (APIError, TypeError, ValueError) as error:
            logger.warning("Gemini agent planning failed; using conservative fallback", exc_info=error)
            plan = _scope_document_query(_fallback_plan(state), state).model_dump(mode="json")
        return {
            "agent_plan": plan,
            "next_action": _planned_action(state, plan),
            "needs_replan": False,
        }
    return {"next_action": _planned_action(state, plan)}


def hybrid_search_node(_state: AgentState) -> AgentState:
    """Emit the pgvector tool choice for Temporal to execute."""
    return {}


@traceable(name="verify_groundedness_node", run_type="chain")
def verify_groundedness_node(state: AgentState) -> AgentState:
    """Apply confidence-verifier output without performing an LLM call here."""
    return {
        "clarification_needed": not state.get("context_sufficient", False),
        "verification_pending": False,
    }


def mcp_search_node(_state: AgentState) -> AgentState:
    """Emit the approved MCP tool choice for Temporal to execute."""
    return {}


@traceable(name="ask_clarification_node", run_type="chain")
def ask_clarification_node(state: AgentState) -> AgentState:
    """Return a safe clarification or no-answer response without external I/O."""
    response = state.get("retrieval_response", {})
    if state.get("iteration_count", 0) >= state.get("max_turns", 5):
        return {"final_answer": "I could not complete this request safely. Please clarify it."}
    plan = state.get("agent_plan", {})
    if plan.get("document_only") and state.get("clarification_needed"):
        return {
            "final_answer": (
                "The answer was not found with sufficient confidence in the documents "
                "attached to this chat."
            )
        }
    if plan.get("clarification_question"):
        return {"final_answer": str(plan["clarification_question"])}
    if state.get("user_choice") and state["user_choice"] != "approve_web_search":
        return {"final_answer": "Web search was not approved. Please clarify your question."}
    return {
        "final_answer": response.get(
            "message", "Please clarify your question before I search outside the uploaded documents."
        )
    }


def synthesize_answer_node(_state: AgentState) -> AgentState:
    """Emit the answer-generation tool choice for Temporal to execute."""
    return {}


def direct_answer_node(_state: AgentState) -> AgentState:
    """Emit a tool-free conversational answer choice for Temporal to execute."""
    return {}
