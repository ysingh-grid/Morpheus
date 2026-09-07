"""Temporal activities for ingestion, retrieval, MCP, and user memory."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import re
import time
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from openai import RateLimitError
from pydantic import BaseModel, Field, ValidationError
from temporalio import activity
from temporalio.exceptions import ApplicationError

from core.config import DEFAULT_MODEL, llm_client
from ingestion.doc_processor import (
    document_content_sha256,
    document_id_for_file,
    process_document,
)
from retrieval.pg_engine import (
    EMBEDDING_BATCH_SIZE,
    EMBEDDING_DIMENSION,
    EMBEDDING_MODEL,
    _database_url,
    _psycopg,
    _child_retrieval_text,
    attach_documents_to_session,
    count_reindexable_children,
    document_ingestion_stats,
    fetch_reindexable_child_batch,
    document_overview_and_join,
    get_full_table,
    ingest_bundle,
    hybrid_search_and_join,
    reindex_child_embedding_batch,
)

from orchestration.mcp_client import call_mcp_tool, resolve_mcp_tool

logger = logging.getLogger(__name__)
INGESTION_STAGING_DIRECTORY = Path(
    os.getenv("MORPHEUS_INGESTION_STAGING_DIR", "uploaded_documents/.ingestion-staging")
)
_DOCLING_OCR_LOCK = Lock()
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
    conversation_summary: str = ""
    document_ids: list[str] = Field(default_factory=list)
    attached_documents: list[dict[str, str]] = Field(default_factory=list)


def _non_retryable(message: str) -> ApplicationError:
    """Return a Temporal error for inputs that a retry cannot repair."""
    return ApplicationError(message, type="InvalidInput", non_retryable=True)


def _write_staging_json(payload: dict[str, Any], suffix: str) -> str:
    """Atomically persist a durable activity payload outside Temporal history."""
    INGESTION_STAGING_DIRECTORY.mkdir(parents=True, exist_ok=True)
    final_path = INGESTION_STAGING_DIRECTORY / f"{uuid4().hex}{suffix}.json"
    temporary_path = final_path.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(payload), encoding="utf-8")
    temporary_path.replace(final_path)
    return str(final_path)


def _read_staging_json(reference: str) -> dict[str, Any]:
    """Load one workflow-owned durable staging payload by its local reference."""
    path = Path(reference)
    if not path.is_file():
        raise _non_retryable(f"Ingestion staging payload is unavailable: {reference}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise _non_retryable(f"Ingestion staging payload is invalid: {reference}") from error
    if not isinstance(payload, dict):
        raise _non_retryable(f"Ingestion staging payload is invalid: {reference}")
    return payload


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
def hash_and_deduplicate_document_activity(file_path: str) -> dict[str, Any]:
    """Hash one upload and report whether its normalized records already exist."""
    path = Path(file_path)
    if not path.is_file():
        raise _non_retryable(f"Document does not exist or is not a file: {file_path}")
    content_sha256 = document_content_sha256(path)
    document_id = document_id_for_file(path)
    existing_stats = document_ingestion_stats(document_id)
    activity.heartbeat(
        {
            "stage": "deduplication_checked",
            "document_id": document_id,
            "already_ingested": existing_stats is not None,
        }
    )
    return {
        "document_id": document_id,
        "content_sha256": content_sha256,
        "filename": path.name,
        "already_ingested": existing_stats is not None,
        "stats": existing_stats or {},
    }


@activity.defn
def parse_docling_layout_activity(file_path: str) -> dict[str, Any]:
    """Parse one document with Docling while heartbeating durable layout progress."""
    path = Path(file_path)
    if not path.is_file():
        raise _non_retryable(f"Document does not exist or is not a file: {file_path}")

    def heartbeat_progress(percent: int, stage: str, details: dict[str, Any]) -> None:
        activity.heartbeat({"stage": stage, "progress": percent, "details": details})

    uses_exclusive_ocr_lock = platform.system() == "Darwin"
    if uses_exclusive_ocr_lock:
        while not _DOCLING_OCR_LOCK.acquire(timeout=30):
            activity.heartbeat({"stage": "waiting_for_exclusive_ocr"})
    try:
        try:
            bundle = process_document(str(path), progress_callback=heartbeat_progress)
        except (OSError, RuntimeError, ValueError) as error:
            raise _non_retryable(f"Unable to parse document layout: {file_path}") from error
    finally:
        if uses_exclusive_ocr_lock:
            _DOCLING_OCR_LOCK.release()
    bundle_reference = _write_staging_json(dict(bundle), ".bundle")
    return {
        "bundle_reference": bundle_reference,
        "document_id": str(bundle["document"]["document_id"]),
        "filename": path.name,
        "children": len(bundle["children"]),
    }


@activity.defn
def generate_embeddings_activity(bundle_reference: str) -> dict[str, Any]:
    """Generate staged child embeddings and back off exponentially on Gemini limits."""
    bundle = _read_staging_json(bundle_reference)
    chunks = bundle.get("children")
    if not isinstance(chunks, list):
        raise _non_retryable("Parsed document bundle has no child chunks.")
    texts = [_child_retrieval_text(str(chunk["text_with_context"])) for chunk in chunks]
    embeddings: list[list[float]] = []
    for offset in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        batch = texts[offset : offset + EMBEDDING_BATCH_SIZE]
        for attempt in range(5):
            try:
                response = llm_client.embeddings.create(
                    model=EMBEDDING_MODEL,
                    input=batch,
                    dimensions=EMBEDDING_DIMENSION,
                )
                embeddings.extend(list(item.embedding) for item in response.data)
                break
            except RateLimitError:
                if attempt == 4:
                    raise
                delay_seconds = 2**attempt
                activity.heartbeat(
                    {
                        "stage": "embedding_rate_limited",
                        "attempt": attempt + 1,
                        "retry_in_seconds": delay_seconds,
                    }
                )
                time.sleep(delay_seconds)
        activity.heartbeat(
            {
                "stage": "embedding_children",
                "completed": min(offset + len(batch), len(texts)),
                "total": len(texts),
            }
        )
    if len(embeddings) != len(chunks):
        raise RuntimeError("Gemini returned a different number of embeddings than chunks.")
    if any(len(embedding) != EMBEDDING_DIMENSION for embedding in embeddings):
        raise RuntimeError("Gemini returned embeddings with an unexpected dimension.")
    embeddings_reference = _write_staging_json({"embeddings": embeddings}, ".embeddings")
    return {"embeddings_reference": embeddings_reference, "children": len(chunks)}


@activity.defn
def count_reindexable_children_activity() -> int:
    """Load the total number of child rows for reindex workflow progress reporting."""
    return count_reindexable_children()


@activity.defn
def fetch_unindexed_chunk_batch_activity(
    batch_size: int, cursor_id: str | None
) -> list[dict[str, str]]:
    """Fetch the next stable child slice for a full embedding rebuild."""
    try:
        batch = fetch_reindexable_child_batch(batch_size, cursor_id)
    except ValueError as error:
        raise _non_retryable(str(error)) from error
    activity.heartbeat(
        {
            "stage": "reindex_batch_fetched",
            "cursor_id": cursor_id,
            "children": len(batch),
        }
    )
    return batch


@activity.defn
def reindex_chunk_batch_activity(chunks: list[dict[str, str]]) -> str:
    """Embed and atomically update one batch, heartbeating sub-batch progress."""
    if not chunks:
        raise _non_retryable("Cannot reindex an empty child batch.")

    def heartbeat_progress(_percent: int, _stage: str, details: dict[str, Any]) -> None:
        activity.heartbeat({"stage": "reindexing_embeddings", **details})

    for attempt in range(5):
        try:
            last_processed_id = reindex_child_embedding_batch(chunks, heartbeat_progress)
            activity.heartbeat(
                {
                    "stage": "reindex_batch_committed",
                    "last_processed_id": last_processed_id,
                    "children": len(chunks),
                }
            )
            return last_processed_id
        except RateLimitError:
            if attempt == 4:
                raise
            delay_seconds = 2**attempt
            activity.heartbeat(
                {
                    "stage": "reindex_rate_limited",
                    "attempt": attempt + 1,
                    "retry_in_seconds": delay_seconds,
                }
            )
            time.sleep(delay_seconds)
    raise RuntimeError("Reindexing exhausted its rate-limit retries.")


def _extract_document_facts(document_name: str, summary: str) -> UserFactExtraction:
    """Extract durable organization, domain, and project context from an ingested document."""
    if not summary.strip():
        return UserFactExtraction(facts=[])
    try:
        completion = llm_client.beta.chat.completions.parse(
            model=DEFAULT_MODEL,
            response_format=UserFactExtraction,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are the document learning engine for a single-user personal knowledge base. "
                        "The user has ingested a document they own or work with into their personal knowledge base. "
                        "Extract durable user context from this document summary and title: "
                        "organization affiliation, active projects, technical domain, or subject area. "
                        "Assign appropriate categories ('organization', 'project', 'domain', 'subject'). "
                        "Return at most 3 high-confidence, broad facts (e.g. fact_key='primary_organization', fact_value='IFC', category='organization'). "
                        "Return an empty facts list if the document is purely generic or does not imply user context."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Document title: {document_name}\nSummary:\n{summary}",
                },
            ],
        )
        return completion.choices[0].message.parsed or UserFactExtraction(facts=[])
    except Exception:
        logger.warning("Document fact extraction failed; continuing ingestion", exc_info=True)
        return UserFactExtraction(facts=[])


@activity.defn
def commit_document_bundle_activity(
    bundle_reference: str,
    embeddings_reference: str,
    user_id: str,
    session_id: str,
) -> dict[str, Any]:
    """Atomically insert a parsed bundle, its embeddings, and its chat attachment."""
    bundle = _read_staging_json(bundle_reference)
    embedding_payload = _read_staging_json(embeddings_reference)
    embeddings = embedding_payload.get("embeddings")
    if not isinstance(embeddings, list):
        raise _non_retryable("Document bundle is missing generated embeddings.")
    try:
        stats = ingest_bundle(bundle, embeddings=embeddings)
    except (OSError, RuntimeError, ValueError) as error:
        raise _non_retryable("Unable to commit document bundle.") from error

    attach_documents_to_session(user_id, session_id, [str(bundle["document"]["document_id"])])
    doc_name = Path(str(bundle["document"]["source_path"])).name
    doc_summary = str(bundle["document"].get("summary", ""))
    extracted = _extract_document_facts(doc_name, doc_summary)
    if extracted.facts:
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
                        for fact in extracted.facts
                    ],
                )
    Path(bundle_reference).unlink(missing_ok=True)
    Path(embeddings_reference).unlink(missing_ok=True)
    activity.heartbeat({"stage": "document_committed", "stats": stats})
    return {
        "document_id": str(bundle["document"]["document_id"]),
        "filename": Path(str(bundle["document"]["source_path"])).name,
        "status": "ingested",
        **stats,
    }


@activity.defn
def attach_existing_document_activity(
    document_id: str, user_id: str, session_id: str
) -> None:
    """Attach a deduplicated document to the requesting chat session."""
    attach_documents_to_session(user_id, session_id, [document_id])


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
    return SessionContext(
        messages=history,
        conversation_summary=(str(session["conversation_summary"]) if session else ""),
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


@activity.defn
def summarize_session_history_activity(
    user_id: str,
    session_id: str,
    messages: list[dict[str, Any]],
) -> str:
    """Compress prior turns into durable planning context without delaying the chat reply."""
    if not user_id.strip() or not session_id.strip():
        raise _non_retryable("user_id and session_id must not be empty.")
    conversation = [
        {
            "role": str(message.get("role", "user")),
            "content": str(message.get("content", ""))[:4_000],
        }
        for message in messages
        if isinstance(message, dict) and str(message.get("content", "")).strip()
    ]
    completion = llm_client.chat.completions.create(
        model=DEFAULT_MODEL,
        temperature=0.0,
        messages=[
            {
                "role": "system",
                "content": (
                    "Summarize this conversation for a future assistant in at most 180 words. "
                    "Include only: the active user topic and named entities; decisions already "
                    "made; answers or constraints established in prior turns. Do not add facts, "
                    "instructions, or commentary."
                ),
            },
            {"role": "user", "content": json.dumps(conversation, ensure_ascii=False)},
        ],
    )
    summary = str(completion.choices[0].message.content or "").strip()[:2_000]
    if not summary:
        raise ValueError("Gemini returned an empty session summary.")
    psycopg = _psycopg()
    with psycopg.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE user_sessions
                SET conversation_summary = %s, updated_at = NOW()
                WHERE user_id = %s AND session_id = %s
                """,
                (summary, user_id, session_id),
            )
    logger.info(
        "Compressed session history persisted",
        extra={
            "user_id": user_id,
            "session_id": session_id,
            "message_count": len(conversation),
        },
    )
    return summary


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


def _validate_tool_arguments(
    tool_name: str, parameters: dict[str, Any], arguments: dict[str, Any]
) -> None:
    """Reject malformed arguments before starting an external MCP server process."""
    if parameters.get("type") != "object":
        raise ValueError(f"MCP tool '{tool_name}' must declare object parameters.")
    required = parameters.get("required", [])
    if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
        raise ValueError(f"MCP tool '{tool_name}' has invalid required parameters.")
    missing = [name for name in required if name not in arguments]
    if missing:
        raise ValueError(f"MCP tool '{tool_name}' is missing required arguments: {missing}.")
    properties = parameters.get("properties", {})
    if parameters.get("additionalProperties") is False and isinstance(properties, dict):
        unexpected = sorted(set(arguments) - set(properties))
        if unexpected:
            raise ValueError(f"MCP tool '{tool_name}' received unknown arguments: {unexpected}.")


@activity.defn
def get_full_table_activity(
    session_id: str,
    doc_id: str,
    table_id: str,
    allowed_document_ids: list[str],
) -> dict[str, str]:
    """Retrieve full normalized table content for an attached document and persist reference."""
    if not session_id.strip() or not doc_id.strip() or not table_id.strip():
        raise _non_retryable("session_id, doc_id, and table_id must not be empty.")
    if doc_id not in allowed_document_ids:
        raise ApplicationError(
            f"Document '{doc_id}' is not attached to this chat session.",
            type="UnauthorizedDocumentAccess",
            non_retryable=True,
        )
    table_data = get_full_table(doc_id, table_id)
    if table_data is None:
        raise ApplicationError(
            f"Table '{table_id}' was not found in document '{doc_id}'.",
            type="TableNotFound",
            non_retryable=True,
        )
    result_id = str(uuid4())
    psycopg = _psycopg()
    with psycopg.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO agent_tool_results (id, session_id, tool_name, result)
                VALUES (%s, %s, %s, %s::jsonb)
                """,
                (result_id, session_id, "get_full_table", json.dumps(table_data)),
            )
    logger.info(
        "Full table retrieved and stored",
        extra={"session_id": session_id, "doc_id": doc_id, "table_id": table_id},
    )
    return {"tool_result_id": result_id, "tool_name": "get_full_table"}


@activity.defn
async def execute_tool_activity(
    session_id: str, tool_name: str, arguments: dict[str, Any]
) -> dict[str, str]:
    """Execute a registry-backed MCP tool and return only its persisted result reference."""
    if not session_id.strip() or not tool_name.strip():
        raise _non_retryable("session_id and tool_name must not be empty.")
    if not isinstance(arguments, dict):
        raise _non_retryable("MCP tool arguments must be a JSON object.")
    if tool_name == "get_full_table":
        doc_id = str(arguments.get("doc_id", ""))
        table_id = str(arguments.get("table_id", ""))
        if not doc_id or not table_id:
            raise ApplicationError(
                "doc_id and table_id are required arguments for get_full_table.",
                type="InvalidInput",
                non_retryable=True,
            )
        psycopg = _psycopg()
        with psycopg.connect(_database_url()) as connection:
            with connection.cursor(row_factory=psycopg.rows.dict_row) as cursor:
                cursor.execute(
                    "SELECT document_ids FROM user_sessions WHERE session_id = %s",
                    (session_id,),
                )
                row = cursor.fetchone()
                if row:
                    raw_ids = row["document_ids"] if isinstance(row, dict) else row[0]
                    allowed_ids = list(raw_ids or [])
                else:
                    allowed_ids = []
        return get_full_table_activity(session_id, doc_id, table_id, allowed_ids)
    try:
        tool = resolve_mcp_tool(tool_name)
        _validate_tool_arguments(tool_name, tool["spec"]["parameters"], arguments)
    except ValueError as error:
        raise ApplicationError(
            f"MCP tool '{tool_name}' is not configured correctly: {error}",
            type="McpConfigurationError",
            non_retryable=True,
        ) from error
    try:
        result = await call_mcp_tool(
            tool["command"],
            tool["args"],
            tool.get("server_tool_name", tool_name),
            arguments,
            server_env=tool["env"],
            timeout_seconds=tool["spec"]["timeout_seconds"],
        )
    except (OSError, ValueError, asyncio.TimeoutError) as error:
        raise ApplicationError(
            f"MCP tool '{tool_name}' failed: {error}", type="McpToolError"
        ) from error
    if result.get("is_error"):
        raise ApplicationError(
            f"MCP tool '{tool_name}' returned an error response.",
            type="McpToolResponseError",
        )
    result_id = str(uuid4())
    psycopg = _psycopg()
    with psycopg.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO agent_tool_results (id, session_id, tool_name, result)
                VALUES (%s, %s, %s, %s::jsonb)
                """,
                (result_id, session_id, tool_name, json.dumps(result)),
            )
    logger.info(
        "Registry-backed MCP result stored",
        extra={"session_id": session_id, "tool_name": tool_name},
    )
    return {"tool_result_id": result_id, "tool_name": tool_name}


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
    """Extract durable user profile, preference, project, and domain facts from the exchange."""
    completion = llm_client.beta.chat.completions.parse(
        model=DEFAULT_MODEL,
        response_format=UserFactExtraction,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are the personalization and memory learning engine for a single-user personal knowledge base. "
                    "All documents and conversations in this system belong to this user. "
                    "Extract durable facts about the user established in this exchange: "
                    "1. Explicit user preferences (e.g. formatting, style, tone, constraints). "
                    "2. User-owned profile details revealed in the conversation or user-owned document evidence "
                    "(e.g. organization, role, current projects, technical stack, research topics, domain expertise). "
                    "Assign a clear category ('preference', 'identity', 'organization', 'project', 'skill', 'domain'). "
                    "Return concise, factual key-value pairs (e.g. fact_key='primary_organization', fact_value='IFC', category='organization'). "
                    "Do not extract transient conversational phrasing or third-party trivia that does not relate to the user. "
                    "Return an empty facts list when there are no user-relevant facts."
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
    user_facts = [
        str(message.get("content", "")).removeprefix("Known user fact ").strip()
        for message in messages
        if isinstance(message, dict)
        and str(message.get("content", "")).startswith("Known user fact")
    ]
    recent_dialogue = [
        message
        for message in messages
        if isinstance(message, dict)
        and not str(message.get("content", "")).startswith("Known user fact")
    ][-12:]
    messages_payload = [
        {
            "role": "system",
            "content": (
                "You are Morpheus, a conversational assistant for this personal knowledge base. "
                "Answer the current question using the supplied document and web evidence, while "
                "respecting relevant conversation context and known user profile facts and preferences. "
                "Tailor explanations, tone, technical depth, and framing to the user's known profile, "
                "organization, and preferences where relevant. "
                "Clearly distinguish uploaded-document facts from web facts. Every factual claim derived "
                "from uploaded-document evidence must end with a visible inline source citation using the "
                "exact supplied filename and page number, for example [Source: handbook.pdf, p. 12] or "
                "[Source: handbook.pdf, pp. 12–13]. Do not use HTML tags, Markdown footnotes, or numbered "
                "[1] citations. Use the narrowest page set that supports the claim: table chunk page_numbers "
                "for table facts, figure bounding-box page_no for figure facts, child page_numbers for child "
                "facts, and parent_page_numbers only when necessary. Never infer a page number. "
                "Do not invent citations, facts, or web results. If a source URL is present in web evidence, "
                "cite it naturally."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Question:\n{query}\n\n"
                f"User Profile & Known Context:\n{json.dumps(user_facts, ensure_ascii=False) if user_facts else 'None'}\n\n"
                f"Conversation:\n{json.dumps(recent_dialogue, ensure_ascii=False)}\n\n"
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
    user_facts = [
        str(message.get("content", "")).removeprefix("Known user fact ").strip()
        for message in messages
        if isinstance(message, dict)
        and str(message.get("content", "")).startswith("Known user fact")
    ]
    recent_dialogue = [
        message
        for message in messages
        if isinstance(message, dict)
        and not str(message.get("content", "")).startswith("Known user fact")
    ][-12:]
    completion = llm_client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are Morpheus, a helpful conversational assistant for this personal knowledge base. "
                    "Respond naturally using the conversation history, user profile facts, and preferences. "
                    "Tailor tone, depth, and framing to the user's known profile and preferences where relevant. "
                    "You may reformat, quote, summarize, or calculate from facts and citations already present "
                    "in a prior assistant answer, but must preserve its source citations and add no new document facts. "
                    "No new evidence-bearing tool result is available for this turn, so never "
                    "claim that you newly inspected an uploaded document or searched the web. "
                    "If a requested tool failed, state that limitation instead of fabricating its result. "
                    "If the user asks for missing details, ask one focused clarification."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Current question:\n{query}\n\n"
                    f"User Profile & Known Context:\n{json.dumps(user_facts, ensure_ascii=False) if user_facts else 'None'}\n\n"
                    f"Recent conversation:\n{json.dumps(recent_dialogue, ensure_ascii=False)}\n\n"
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
