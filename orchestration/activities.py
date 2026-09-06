"""Temporal activities for ingestion, retrieval, MCP, and user memory."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, ValidationError
from temporalio import activity
from temporalio.exceptions import ApplicationError

from core.config import DEFAULT_MODEL, llm_client
from ingestion.doc_processor import process_document
from retrieval.pg_engine import (
    _database_url,
    _psycopg,
    document_overview_and_join,
    ingest_bundle,
    hybrid_search_and_join,
)

from orchestration.mcp_client import call_mcp_tool

logger = logging.getLogger(__name__)
SOURCE_CITATION_PATTERN = re.compile(
    r"\[Source:\s*(?P<document>.+?),\s*pp?\.\s*(?P<pages>[0-9,\s\-–]+)\]",
    re.IGNORECASE,
)
OPENWEBUI_UPLOAD_PREFIX = re.compile(
    r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}_", re.IGNORECASE
)
OPENWEBUI_UTILITY_TASK_MARKERS = (
    "generate a concise title summarizing the chat history",
    "suggest 3-5 relevant follow-up questions or prompts",
    "generate 1-3 broad tags categorizing the main themes",
    "analyze the chat history to determine the necessity of generating search queries",
)


class UserFact(BaseModel):
    """One durable preference or entity explicitly disclosed by a user."""

    fact_key: str = Field(min_length=1, max_length=128)
    fact_value: str = Field(min_length=1, max_length=1000)
    category: str = Field(min_length=1, max_length=64)


class UserFactExtraction(BaseModel):
    """Structured output persisted by the user-fact activity."""

    facts: list[UserFact] = Field(default_factory=list, max_length=20)


class ContextSufficiency(BaseModel):
    """Structured borderline-confidence assessment for retrieved context."""

    is_context_sufficient: bool
    reason: str = Field(min_length=1, max_length=500)


class SessionContext(BaseModel):
    """Compact conversational memory and uploaded-document scope for one chat."""

    messages: list[dict[str, str]] = Field(default_factory=list)
    document_ids: list[str] = Field(default_factory=list)
    attached_documents: list[dict[str, str]] = Field(default_factory=list)


def _non_retryable(message: str) -> ApplicationError:
    """Return a Temporal error for inputs that a retry cannot repair."""
    return ApplicationError(message, type="InvalidInput", non_retryable=True)


def _is_openwebui_utility_prompt(prompt: str) -> bool:
    """Identify Open WebUI metadata-generation prompts that are not user turns."""
    normalized = prompt.strip().lower()
    return (
        normalized.startswith("### task:")
        and "### guidelines:" in normalized
        and "### output:" in normalized
        and "### chat history:" in normalized
        and any(marker in normalized for marker in OPENWEBUI_UTILITY_TASK_MARKERS)
    )


@activity.defn
def ingest_document_activity(file_path: str) -> dict[str, int]:
    """Process one local document and atomically load its normalized bundle."""
    path = Path(file_path)
    if not path.is_file():
        raise _non_retryable(f"Document does not exist or is not a file: {file_path}")
    try:
        bundle = process_document(str(path))
        stats = ingest_bundle(bundle)
    except (OSError, ValueError) as error:
        raise _non_retryable(f"Unable to ingest document: {file_path}") from error
    logger.info(
        "Temporal document ingestion completed", extra={"file_path": str(path), **stats}
    )
    return stats


@activity.defn
def run_pgvector_retrieval_activity(query: str, top_k: int = 5) -> dict[str, Any]:
    """Retrieve evidence together with the confidence decision that produced it."""
    if not query.strip():
        raise _non_retryable("Retrieval query must not be empty.")
    if top_k < 1:
        raise _non_retryable("Retrieval top_k must be at least 1.")
    response = hybrid_search_and_join(query, top_k)
    logger.info(
        "Temporal retrieval completed",
        extra={
            "status": response["status"],
            "evidence_count": len(response["evidence"]),
        },
    )
    return dict(response)


@activity.defn
async def run_agent_graph_activity(state: dict[str, Any]) -> dict[str, Any]:
    """Execute one bounded, side-effect-free LangGraph decision pass."""
    from agent.graph import compile_agent_graph

    result = await compile_agent_graph().ainvoke(state, {"recursion_limit": 8})
    logger.info(
        "LangGraph agent completed",
        extra={
            "clarification_needed": bool(result.get("clarification_needed")),
            "has_final_answer": bool(result.get("final_answer")),
        },
    )
    return dict(result)


def _history_for_user(user_id: str, session_id: str) -> SessionContext:
    """Load compact durable memories and document scope for the current session."""
    psycopg = _psycopg()
    with psycopg.connect(_database_url()) as connection:
        with connection.cursor(row_factory=psycopg.rows.dict_row) as cursor:
            cursor.execute(
                """
                SELECT fact_key, fact_value, category
                FROM user_facts
                WHERE user_id = %s
                ORDER BY updated_at DESC, fact_key
                """,
                (user_id,),
            )
            facts = list(cursor.fetchall())
            cursor.execute(
                """
                SELECT conversation_summary, document_ids
                FROM user_sessions
                WHERE user_id = %s AND session_id = %s
                """,
                (user_id, session_id),
            )
            session = cursor.fetchone()
            document_ids = list(session["document_ids"] or []) if session else []
            attached_documents: list[dict[str, str]] = []
            if document_ids:
                cursor.execute(
                    """
                    SELECT id, source_path, summary
                    FROM documents
                    WHERE id = ANY(%s)
                    ORDER BY id
                    """,
                    (document_ids,),
                )
                attached_documents = [
                    {
                        "id": str(document["id"]),
                        "name": Path(str(document["source_path"])).stem,
                        "summary": str(document["summary"]),
                    }
                    for document in cursor.fetchall()
                ]
    history = [
        {
            "role": "system",
            "content": (
                "Known user fact "
                f"({fact['category']}): {fact['fact_key']} = {fact['fact_value']}"
            ),
        }
        for fact in facts
    ]
    if session and session["conversation_summary"]:
        history.append({"role": "system", "content": session["conversation_summary"]})
    return SessionContext(
        messages=history,
        document_ids=document_ids,
        attached_documents=attached_documents,
    )


@activity.defn
def load_history_activity(user_id: str, session_id: str) -> dict[str, Any]:
    """Load history and document scope separately from agent reasoning retries."""
    if not user_id.strip() or not session_id.strip():
        raise _non_retryable("user_id and session_id must not be empty.")
    return _history_for_user(user_id, session_id).model_dump(mode="json")


@activity.defn
def persist_session_turn_activity(
    user_id: str,
    session_id: str,
    messages: list[dict[str, Any]],
    answer: str,
) -> None:
    """Upsert a compact, already-sanitized summary of the latest chat turn."""
    if not user_id.strip() or not session_id.strip():
        raise _non_retryable("user_id and session_id must not be empty.")
    latest_user_message = next(
        (
            str(message.get("content", ""))
            for message in reversed(messages)
            if message.get("role") == "user"
        ),
        "",
    )
    if _is_openwebui_utility_prompt(latest_user_message):
        logger.info(
            "Skipped Open WebUI utility prompt session persistence",
            extra={"user_id": user_id, "session_id": session_id},
        )
        return
    summary = (
        f"Latest user query: {latest_user_message}\nLatest assistant answer: {answer}"[
            :8000
        ]
    )
    psycopg = _psycopg()
    with psycopg.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO user_sessions (user_id, session_id, conversation_summary)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id, session_id) DO UPDATE
                SET conversation_summary = EXCLUDED.conversation_summary,
                    updated_at = NOW()
                """,
                (user_id, session_id, summary),
            )
    logger.info(
        "User session summary upserted",
        extra={"user_id": user_id, "session_id": session_id},
    )


def _compact_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    """Return reference-only evidence suitable for Temporal workflow state."""
    table_chunk_ids: list[str] = []
    for chunk in evidence["matched_table_chunks"]:
        chunk_id = chunk.get("table_chunk_id", chunk.get("id"))
        if not isinstance(chunk_id, str) or not chunk_id:
            raise ValueError("Matched table chunk is missing its identifier.")
        table_chunk_ids.append(chunk_id)
    return {
        "chunk_id": evidence["chunk_id"],
        "parent_id": evidence["parent_id"],
        "document_id": evidence["document_id"],
        "page_numbers": evidence.get("page_numbers", []),
        "parent_page_numbers": evidence.get("parent_page_numbers", []),
        "rrf_score": evidence["rrf_score"],
        "vector_distance": evidence["vector_distance"],
        "lexical_match": evidence["lexical_match"],
        "rrf_score_margin": evidence["rrf_score_margin"],
        "reranker_score": evidence["reranker_score"],
        "matched_table_chunk_ids": table_chunk_ids,
    }


def _is_borderline_confidence(response: dict[str, Any]) -> bool:
    """Restrict LLM verification to ambiguous retrieval near existing score gates."""
    if response["status"] != "clarification_needed":
        return False
    confidence = response["confidence"]
    distance = confidence["vector_distance"]
    return (
        confidence["rrf_score"] >= 0.012
        or (distance is not None and distance <= 0.46)
        or confidence["lexical_match"]
    )


@activity.defn
def run_agent_retrieval_activity(
    query: str,
    top_k: int = 5,
    document_ids: list[str] | None = None,
    document_lookup: str = "semantic",
) -> dict[str, Any]:
    """Retrieve from this chat's documents and return compact evidence references."""
    if not query.strip():
        raise _non_retryable("Retrieval query must not be empty.")
    if not document_ids:
        return {
            "status": "not_found",
            "message": "No documents are attached to this chat.",
            "confidence": {},
            "evidence": [],
        }
    if document_lookup == "overview":
        response = document_overview_and_join(document_ids, min(top_k, 2))
    else:
        response = hybrid_search_and_join(
            query,
            top_k,
            include_ambiguous_evidence=True,
            document_ids=document_ids,
            confidence_policy=document_lookup,
        )
    return {
        "status": response["status"],
        "message": response["message"],
        "confidence": response["confidence"],
        "evidence": [_compact_evidence(item) for item in response["evidence"]],
    }


@activity.defn
def verify_borderline_confidence_activity(
    query: str,
    retrieval_response: dict[str, Any],
    evidence_references: list[dict[str, Any]],
    force_verification: bool = False,
) -> bool:
    """Use Gemini for borderline hits or mandatory document-only sufficiency checks."""
    if not force_verification and not _is_borderline_confidence(retrieval_response):
        return False
    evidence = _load_evidence_by_references(evidence_references[:2])
    if not evidence:
        return False
    completion = llm_client.beta.chat.completions.parse(
        model=DEFAULT_MODEL,
        response_format=ContextSufficiency,
        messages=[
            {
                "role": "system",
                "content": (
                    "Decide whether the supplied uploaded-document context alone can answer "
                    "the question accurately. Return true only when it directly supports a "
                    "complete answer."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Question:\n{query}\n\n"
                    f"Candidate context:\n{json.dumps(evidence, ensure_ascii=False)}"
                ),
            },
        ],
    )
    assessment = completion.choices[0].message.parsed
    if assessment is None:
        raise ValueError(
            "Gemini did not return a structured context-sufficiency assessment."
        )
    logger.info(
        "Borderline retrieval verified",
        extra={"is_context_sufficient": assessment.is_context_sufficient},
    )
    return assessment.is_context_sufficient


@activity.defn
async def execute_mcp_tool_activity(
    tool_name: str, args: dict[str, Any]
) -> dict[str, Any]:
    """Call the configured MCP server from an activity worker."""
    server_command = os.getenv("MCP_SERVER_COMMAND")
    server_args = shlex.split(os.getenv("MCP_SERVER_ARGS", ""))
    if not server_command or not server_args:
        raise ApplicationError(
            "MCP_SERVER_COMMAND and MCP_SERVER_ARGS must configure a server exposing "
            f"the requested '{tool_name}' tool.",
            type="McpConfigurationError",
            non_retryable=True,
        )
    try:
        result = await call_mcp_tool(server_command, server_args, tool_name, args)
    except (OSError, ValueError, asyncio.TimeoutError) as error:
        raise ApplicationError(
            f"MCP tool '{tool_name}' failed: {error}", type="McpToolError"
        ) from error
    if result.get("is_error"):
        raise ApplicationError(
            f"MCP tool '{tool_name}' returned an error response.",
            type="McpToolResponseError",
        )
    logger.info("Temporal MCP tool completed", extra={"tool_name": tool_name})
    return result


@activity.defn
async def execute_agent_mcp_activity(session_id: str, query: str) -> dict[str, str]:
    """Store a Tavily payload outside workflow state and return its reference."""
    if not session_id.strip() or not query.strip():
        raise _non_retryable("session_id and query must not be empty.")
    result = await execute_mcp_tool_activity("tavily_search", {"query": query})
    result_id = str(uuid4())
    psycopg = _psycopg()
    with psycopg.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO agent_tool_results (id, session_id, tool_name, result)
                VALUES (%s, %s, %s, %s::jsonb)
                """,
                (result_id, session_id, "tavily_search", json.dumps(result)),
            )
    logger.info(
        "Agent MCP result stored",
        extra={"session_id": session_id, "tool_name": "tavily_search"},
    )
    return {"tool_result_id": result_id, "tool_name": "tavily_search"}


def _load_evidence_by_references(
    references: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Hydrate only selected parent, child, table, and figure records for an answer."""
    if not references:
        return []
    parent_ids = list(dict.fromkeys(item["parent_id"] for item in references))
    child_ids = list(dict.fromkeys(item["chunk_id"] for item in references))
    table_chunk_ids = list(
        dict.fromkeys(
            chunk_id
            for item in references
            for chunk_id in item.get("matched_table_chunk_ids", [])
        )
    )
    psycopg = _psycopg()
    with psycopg.connect(_database_url()) as connection:
        with connection.cursor(row_factory=psycopg.rows.dict_row) as cursor:
            cursor.execute(
                """
                SELECT
                    parent.id,
                    parent.doc_id,
                    parent.parent_text,
                    parent.page_numbers,
                    parent.figure_ids,
                    parent.table_ids,
                    document.source_path,
                    document.summary AS document_summary
                FROM parents AS parent
                JOIN documents AS document ON document.id = parent.doc_id
                WHERE parent.id = ANY(%s)
                """,
                (parent_ids,),
            )
            parents = {record["id"]: record for record in cursor.fetchall()}
            cursor.execute(
                """
                SELECT id, parent_id, text_with_context, page_numbers
                FROM children
                WHERE id = ANY(%s)
                """,
                (child_ids,),
            )
            children = {record["id"]: record for record in cursor.fetchall()}
            cursor.execute(
                """
                SELECT p.id AS parent_id, f.id, f.caption, f.bounding_boxes
                FROM parents AS p
                JOIN figures AS f
                  ON f.doc_id = p.doc_id AND f.id = ANY(p.figure_ids)
                WHERE p.id = ANY(%s)
                """,
                (parent_ids,),
            )
            figures: dict[str, list[dict[str, Any]]] = {
                parent_id: [] for parent_id in parent_ids
            }
            for record in cursor.fetchall():
                figures[record.pop("parent_id")].append(record)
            cursor.execute(
                """
                SELECT
                    p.id AS parent_id,
                    t.id,
                    t.markdown,
                    t.heading,
                    t.caption,
                    t.context,
                    t.bounding_boxes
                FROM parents AS p
                JOIN tables AS t
                  ON t.doc_id = p.doc_id AND t.id = ANY(p.table_ids)
                WHERE p.id = ANY(%s)
                """,
                (parent_ids,),
            )
            tables: dict[str, list[dict[str, Any]]] = {
                parent_id: [] for parent_id in parent_ids
            }
            for record in cursor.fetchall():
                tables[record.pop("parent_id")].append(record)
            table_chunks: dict[str, dict[str, Any]] = {}
            if table_chunk_ids:
                cursor.execute(
                    """
                    SELECT id, table_id, row_start, row_end, text_with_context, page_numbers
                    FROM table_chunks
                    WHERE id = ANY(%s)
                    """,
                    (table_chunk_ids,),
                )
                table_chunks = {record["id"]: record for record in cursor.fetchall()}
    hydrated: list[dict[str, Any]] = []
    for reference in references:
        parent = parents.get(reference["parent_id"])
        child = children.get(reference["chunk_id"])
        if parent is None or child is None:
            continue
        hydrated.append(
            {
                **reference,
                "document_name": _display_document_name(str(parent["source_path"])),
                "document_summary": parent["document_summary"],
                "child_text": _page_grounded_child_text(child["text_with_context"]),
                "page_numbers": list(child["page_numbers"] or []),
                "parent_text": parent["parent_text"],
                "parent_page_numbers": list(parent["page_numbers"] or []),
                "figures": figures.get(parent["id"], []),
                "tables": tables.get(parent["id"], []),
                "matched_table_chunks": [
                    table_chunks[chunk_id]
                    for chunk_id in reference.get("matched_table_chunk_ids", [])
                    if chunk_id in table_chunks
                ],
            }
        )
    return hydrated


def _load_mcp_results(references: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Hydrate stored tool payloads only while generating the answer."""
    result_ids = [
        item["tool_result_id"] for item in references if "tool_result_id" in item
    ]
    if not result_ids:
        return []
    psycopg = _psycopg()
    with psycopg.connect(_database_url()) as connection:
        with connection.cursor(row_factory=psycopg.rows.dict_row) as cursor:
            cursor.execute(
                "SELECT id, tool_name, result FROM agent_tool_results WHERE id = ANY(%s)",
                (result_ids,),
            )
            results = {record["id"]: record for record in cursor.fetchall()}
    return [results[result_id] for result_id in result_ids if result_id in results]


def _page_grounded_child_text(text_with_context: str) -> str:
    """Remove the page-less global summary before using a child as cited evidence."""
    summary_prefix = "Document summary:"
    if not text_with_context.startswith(summary_prefix):
        return text_with_context
    _, separator, child_text = text_with_context.partition("\n\n")
    return child_text if separator else ""


def _display_document_name(source_path: str) -> str:
    """Hide Open WebUI's opaque upload prefix from human-facing citations."""
    return OPENWEBUI_UPLOAD_PREFIX.sub("", Path(source_path).name)


def _document_evidence_pages(evidence: list[dict[str, Any]]) -> set[int]:
    """Collect every page number that the answer is allowed to cite."""
    pages: set[int] = set()
    for item in evidence:
        pages.update(int(page) for page in item.get("page_numbers", []))
        pages.update(int(page) for page in item.get("parent_page_numbers", []))
        for table_chunk in item.get("matched_table_chunks", []):
            pages.update(int(page) for page in table_chunk.get("page_numbers", []))
        for asset in [*item.get("figures", []), *item.get("tables", [])]:
            for bounding_box in asset.get("bounding_boxes", []):
                page_no = bounding_box.get("page_no")
                if isinstance(page_no, int):
                    pages.add(page_no)
    return pages


def _document_evidence_pages_by_name(
    evidence: list[dict[str, Any]],
) -> dict[str, set[int]]:
    """Group explicit page provenance by source filename for visible answer citations."""
    pages_by_name: dict[str, set[int]] = {}
    for item in evidence:
        document_name = item.get("document_name")
        if not isinstance(document_name, str) or not document_name:
            continue
        pages_by_name.setdefault(document_name, set()).update(
            _document_evidence_pages([item])
        )
    return {name: pages for name, pages in pages_by_name.items() if pages}


def _source_citations_are_valid(
    answer: str, allowed_pages_by_name: dict[str, set[int]]
) -> bool:
    """Require visible source citations and reject unavailable document-page references."""
    citations = list(SOURCE_CITATION_PATTERN.finditer(answer))
    if not citations:
        return False
    cited_pages_by_name: dict[str, set[int]] = {}
    for citation in citations:
        document_name = citation.group("document").strip()
        cited_pages = cited_pages_by_name.setdefault(document_name, set())
        for start, end in re.findall(
            r"(\d+)(?:\s*[-–]\s*(\d+))?", citation.group("pages")
        ):
            first_page = int(start)
            last_page = int(end or start)
            if first_page > last_page:
                return False
            cited_pages.update(range(first_page, last_page + 1))
    return all(
        bool(pages) and pages <= allowed_pages_by_name.get(document_name, set())
        for document_name, pages in cited_pages_by_name.items()
    )


def _extract_facts(prompt: str, response: str) -> UserFactExtraction:
    """Ask Gemini for only user facts explicitly stated in the exchange."""
    completion = llm_client.beta.chat.completions.parse(
        model=DEFAULT_MODEL,
        response_format=UserFactExtraction,
        messages=[
            {
                "role": "system",
                "content": (
                    "Extract only durable user preferences or user-owned entities explicitly "
                    "stated in the conversation. Never infer facts from document evidence. "
                    "Return an empty facts list when there are no such facts."
                ),
            },
            {
                "role": "user",
                "content": f"User prompt:\n{prompt}\n\nAssistant response:\n{response}",
            },
        ],
    )
    parsed = completion.choices[0].message.parsed
    if parsed is None:
        raise ValueError("Gemini did not return structured user facts.")
    return parsed


@activity.defn
def generate_answer_activity(
    query: str,
    evidence_references: list[dict[str, Any]],
    mcp_result_references: list[dict[str, Any]],
    messages: list[dict[str, Any]],
) -> str:
    """Hydrate selected tool results and let the agent synthesize one answer."""
    if not query.strip():
        raise _non_retryable("Answer query must not be empty.")
    evidence = _load_evidence_by_references(evidence_references)
    mcp_results = _load_mcp_results(mcp_result_references)
    if not evidence and not mcp_results:
        raise _non_retryable("Grounded evidence is required to generate an answer.")
    messages_payload = [
        {
            "role": "system",
            "content": (
                "You are Morpheus, a conversational assistant. Answer the current question "
                "using the supplied document and web evidence, while respecting relevant "
                "conversation context. Clearly distinguish uploaded-document facts from web "
                "facts. Every factual claim derived from uploaded-document evidence must end "
                "with a visible inline source citation using the exact supplied filename and "
                "page number, for example [Source: handbook.pdf, p. 12] or "
                "[Source: handbook.pdf, pp. 12–13]. Do not use HTML tags, Markdown footnotes, "
                "or numbered [1] citations. Use the narrowest page "
                "set that supports the claim: table chunk page_numbers for table facts, figure "
                "bounding-box page_no for figure facts, child page_numbers for child facts, "
                "and parent_page_numbers only when necessary. Never infer a page number. "
                "Do not invent citations, facts, or web results. If a source URL is present "
                "in web evidence, cite it naturally."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Question:\n{query}\n\n"
                f"Conversation:\n{json.dumps(messages[-12:], ensure_ascii=False)}\n\n"
                f"Grounded document evidence:\n{json.dumps(evidence, ensure_ascii=False)}\n\n"
                f"Web evidence:\n{json.dumps(mcp_results, ensure_ascii=False)}"
            ),
        },
    ]
    completion = llm_client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=messages_payload,
    )
    answer = completion.choices[0].message.content
    if not answer:
        raise ValueError("Gemini did not return an answer.")
    allowed_pages_by_name = _document_evidence_pages_by_name(evidence)
    if allowed_pages_by_name and not _source_citations_are_valid(
        answer, allowed_pages_by_name
    ):
        repair = llm_client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                *messages_payload,
                {"role": "assistant", "content": answer},
                {
                    "role": "user",
                    "content": (
                        "Revise the draft so every uploaded-document factual claim ends with a "
                        "visible inline citation in the form [Source: filename, p. 12]. Do not "
                        "use HTML, Markdown footnotes, or numbered citations. Use only this "
                        "document-page map: "
                        f"{ {name: sorted(pages) for name, pages in allowed_pages_by_name.items()} }. "
                        "Return only the revised answer."
                    ),
                },
            ],
        )
        answer = repair.choices[0].message.content
        if not answer or not _source_citations_are_valid(answer, allowed_pages_by_name):
            raise ValueError("Gemini did not produce valid document-source citations.")
    logger.info(
        "Grounded answer generated",
        extra={"evidence_count": len(evidence), "mcp_result_count": len(mcp_results)},
    )
    return answer


@activity.defn
def generate_direct_answer_activity(
    query: str,
    messages: list[dict[str, Any]],
    tool_errors: dict[str, str],
) -> str:
    """Let the central agent answer conversationally without forcing a tool call."""
    if not query.strip():
        raise _non_retryable("Answer query must not be empty.")
    completion = llm_client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are Morpheus, a helpful conversational assistant. Respond naturally "
                    "using the conversation history. You may reformat, quote, summarize, or "
                    "calculate from facts and citations already present in a prior assistant "
                    "answer, but must preserve its source citations and add no new document facts. "
                    "No new evidence-bearing tool result is available for this turn, so never "
                    "claim that you newly inspected an uploaded "
                    "document or searched the web. If a requested tool failed, state that "
                    "limitation instead of fabricating its result. If the user asks for missing "
                    "details, ask one focused clarification."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Current question:\n{query}\n\n"
                    f"Recent conversation:\n{json.dumps(messages[-12:], ensure_ascii=False)}\n\n"
                    f"Tool failures:\n{json.dumps(tool_errors, ensure_ascii=False)}"
                ),
            },
        ],
    )
    answer = completion.choices[0].message.content
    if not answer:
        raise ValueError("Gemini did not return a conversational answer.")
    logger.info("Direct conversational answer generated")
    return answer


@activity.defn
def extract_user_facts_activity(user_id: str, prompt: str, response: str) -> bool:
    """Extract explicitly stated user facts and upsert them into PostgreSQL."""
    if not user_id.strip():
        raise _non_retryable("user_id must not be empty.")
    try:
        extraction = _extract_facts(prompt, response)
    except (ValidationError, ValueError) as error:
        raise _non_retryable(
            "Could not validate Gemini structured user facts."
        ) from error
    if not extraction.facts:
        logger.info("No durable user facts extracted", extra={"user_id": user_id})
        return False

    psycopg = _psycopg()
    with psycopg.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO user_facts (user_id, fact_key, fact_value, category)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id, fact_key) DO UPDATE
                SET fact_value = EXCLUDED.fact_value,
                    category = EXCLUDED.category,
                    updated_at = NOW()
                """,
                [
                    (user_id, fact.fact_key, fact.fact_value, fact.category)
                    for fact in extraction.facts
                ],
            )
    logger.info(
        "User facts upserted",
        extra={"user_id": user_id, "count": len(extraction.facts)},
    )
    return True
