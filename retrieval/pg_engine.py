"""Load normalized preprocessor bundles and retrieve grounded RAG evidence.

This module keeps vector search and relational context in PostgreSQL.  It uses a
single RRF CTE query to fuse child-vector and full-text ranks, then joins the
winning children to their parent blocks, figures, and tables atomically.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Literal, TypedDict

from core.config import llm_client

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL_NAME", "gemini-embedding-001")
EMBEDDING_DIMENSION = 1536
EMBEDDING_BATCH_SIZE = 100
RRF_K = 60
RRF_CANDIDATE_MULTIPLIER = 10
MIN_RRF_SCORE = float(os.getenv("RETRIEVAL_MIN_RRF_SCORE", "0.016"))
MAX_VECTOR_DISTANCE = float(os.getenv("RETRIEVAL_MAX_VECTOR_DISTANCE", "0.400"))
MIN_RRF_SCORE_MARGIN = float(os.getenv("RETRIEVAL_MIN_RRF_SCORE_MARGIN", "0.0002"))
SCHEMA_PATH = Path(__file__).with_name("schema.sql")


class GroundedEvidence(TypedDict):
    """One reranked child hit with its normalized source evidence."""

    chunk_id: str
    child_text: str
    parent_id: str
    parent_text: str
    document_id: str
    rrf_score: float
    vector_distance: float | None
    lexical_match: bool
    rrf_score_margin: float
    reranker_score: float
    figures: list[dict[str, Any]]
    tables: list[dict[str, Any]]
    matched_table_chunks: list[dict[str, Any]]


class RetrievalConfidence(TypedDict):
    """Calibrated quality signals for the strongest RRF candidate."""

    status: Literal["grounded", "not_found", "clarification_needed"]
    rrf_score: float
    vector_distance: float | None
    lexical_match: bool
    rrf_score_margin: float
    reasons: list[str]


class RetrievalResponse(TypedDict):
    """User-facing retrieval result with evidence only when it passes confidence checks."""

    status: Literal["grounded", "not_found", "clarification_needed"]
    message: str
    confidence: RetrievalConfidence
    evidence: list[GroundedEvidence]


HYBRID_SEARCH_AND_JOIN_SQL = """
WITH search_input AS (
    SELECT
        %s::vector AS query_embedding,
        websearch_to_tsquery('english', %s) AS query_terms,
        %s::text[] AS document_ids
),
vector_candidates AS (
    SELECT
        child.parent_id,
        child.embedding <=> input.query_embedding AS distance
    FROM children AS child
    CROSS JOIN search_input AS input
    WHERE cardinality(input.document_ids) = 0
       OR child.doc_id = ANY(input.document_ids)
    ORDER BY child.embedding <=> input.query_embedding
    LIMIT %s
),
vector_scores AS (
    SELECT
        parent_id,
        MIN(distance) AS distance
    FROM vector_candidates
    GROUP BY parent_id
),
vector_ranked AS (
    SELECT
        parent_id,
        ROW_NUMBER() OVER (ORDER BY distance) AS rank_position
    FROM vector_scores
    ORDER BY distance
),
child_fts_scores AS (
    SELECT
        child.parent_id,
        MAX(ts_rank_cd(child.fts_content, input.query_terms)) AS lexical_score
    FROM children AS child
    CROSS JOIN search_input AS input
    WHERE (cardinality(input.document_ids) = 0 OR child.doc_id = ANY(input.document_ids))
      AND child.fts_content @@ input.query_terms
    GROUP BY child.parent_id
),
child_fts_ranked AS (
    SELECT
        parent_id,
        ROW_NUMBER() OVER (ORDER BY lexical_score DESC) AS rank_position
    FROM child_fts_scores
    ORDER BY lexical_score DESC
    LIMIT %s
),
table_fts_raw AS (
    SELECT
        parent.id AS parent_id,
        table_chunk.id AS table_chunk_id,
        ts_rank_cd(table_chunk.fts_content, input.query_terms) AS lexical_score
    FROM table_chunks AS table_chunk
    JOIN tables AS source_table
      ON source_table.doc_id = table_chunk.doc_id
     AND source_table.id = table_chunk.table_id
    JOIN parents AS parent
      ON parent.doc_id = source_table.doc_id
     AND source_table.id = ANY(parent.table_ids)
    CROSS JOIN search_input AS input
    WHERE (cardinality(input.document_ids) = 0 OR table_chunk.doc_id = ANY(input.document_ids))
      AND table_chunk.fts_content @@ input.query_terms
),
table_fts_scores AS (
    SELECT
        parent_id,
        MAX(lexical_score) AS lexical_score
    FROM table_fts_raw
    GROUP BY parent_id
),
table_match_chunks AS (
    SELECT DISTINCT ON (parent_id)
        parent_id,
        table_chunk_id
    FROM table_fts_raw
    ORDER BY parent_id, lexical_score DESC, table_chunk_id
),
table_fts_ranked AS (
    SELECT
        parent_id,
        ROW_NUMBER() OVER (ORDER BY lexical_score DESC) AS rank_position
    FROM table_fts_scores
    ORDER BY lexical_score DESC
    LIMIT %s
),
rrf_scores AS (
    SELECT parent_id, SUM(1.0 / (%s + rank_position)) AS rrf_score
    FROM (
        SELECT parent_id, rank_position FROM vector_ranked
        UNION ALL
        SELECT parent_id, rank_position FROM child_fts_ranked
        UNION ALL
        SELECT parent_id, rank_position FROM table_fts_ranked
    ) AS ranked
    GROUP BY parent_id
),
ranked_parents AS (
    SELECT parent_id, rrf_score
         , rrf_score - LEAD(rrf_score) OVER (ORDER BY rrf_score DESC) AS rrf_score_margin
    FROM rrf_scores
),
top_parents AS (
    SELECT parent_id, rrf_score, COALESCE(rrf_score_margin, rrf_score) AS rrf_score_margin
    FROM ranked_parents
    ORDER BY rrf_score DESC
    LIMIT %s
)
SELECT
    child.chunk_id,
    child.child_text,
    parent.id AS parent_id,
    parent.parent_text,
    parent.doc_id AS document_id,
    top_parents.rrf_score,
    vector_scores.distance AS vector_distance,
    (
        COALESCE(child_fts_scores.lexical_score, 0) > 0
        OR COALESCE(table_fts_scores.lexical_score, 0) > 0
    ) AS lexical_match,
    top_parents.rrf_score_margin,
    COALESCE(figure_assets.figures, '[]'::jsonb) AS figures,
    COALESCE(table_assets.tables, '[]'::jsonb) AS tables,
    COALESCE(matched_table_assets.table_chunks, '[]'::jsonb) AS matched_table_chunks
FROM top_parents
JOIN parents AS parent ON parent.id = top_parents.parent_id
LEFT JOIN vector_scores ON vector_scores.parent_id = parent.id
LEFT JOIN child_fts_scores ON child_fts_scores.parent_id = parent.id
LEFT JOIN table_fts_scores ON table_fts_scores.parent_id = parent.id
CROSS JOIN search_input AS input
JOIN LATERAL (
    SELECT
        source_child.id AS chunk_id,
        source_child.text_with_context AS child_text
    FROM children AS source_child
    WHERE source_child.parent_id = parent.id
    ORDER BY source_child.embedding <=> input.query_embedding
    LIMIT 1
) AS child ON TRUE
LEFT JOIN LATERAL (
    SELECT jsonb_agg(
        jsonb_build_object(
            'figure_id', figure.id,
            'caption', figure.caption,
            'bounding_boxes', figure.bounding_boxes
        ) ORDER BY figure.id
    ) AS figures
    FROM figures AS figure
    WHERE figure.doc_id = parent.doc_id
      AND figure.id = ANY(parent.figure_ids)
) AS figure_assets ON TRUE
LEFT JOIN LATERAL (
    SELECT jsonb_agg(
        jsonb_build_object(
            'table_id', source_table.id,
            'markdown', source_table.markdown,
            'heading', source_table.heading,
            'caption', source_table.caption,
            'context', source_table.context,
            'bounding_boxes', source_table.bounding_boxes,
            'row_count', source_table.row_count,
            'column_count', source_table.column_count,
            'table_chunks', COALESCE(chunk_assets.table_chunks, '[]'::jsonb)
        ) ORDER BY source_table.id
    ) AS tables
    FROM tables AS source_table
    LEFT JOIN LATERAL (
        SELECT jsonb_agg(
            jsonb_build_object(
                'table_chunk_id', table_chunk.id,
                'row_start', table_chunk.row_start,
                'row_end', table_chunk.row_end,
                'text_with_context', table_chunk.text_with_context
            ) ORDER BY table_chunk.row_start, table_chunk.id
        ) AS table_chunks
        FROM table_chunks AS table_chunk
        WHERE table_chunk.doc_id = source_table.doc_id
          AND table_chunk.table_id = source_table.id
    ) AS chunk_assets ON TRUE
    WHERE source_table.doc_id = parent.doc_id
      AND source_table.id = ANY(parent.table_ids)
) AS table_assets ON TRUE
LEFT JOIN LATERAL (
    SELECT jsonb_agg(
        jsonb_build_object(
            'table_chunk_id', matched_table_chunk.id,
            'table_id', matched_table_chunk.table_id,
            'row_start', matched_table_chunk.row_start,
            'row_end', matched_table_chunk.row_end,
            'text_with_context', matched_table_chunk.text_with_context
        )
    ) AS table_chunks
    FROM table_match_chunks AS table_match
    JOIN table_chunks AS matched_table_chunk
      ON matched_table_chunk.doc_id = parent.doc_id
     AND matched_table_chunk.id = table_match.table_chunk_id
    WHERE table_match.parent_id = parent.id
) AS matched_table_assets ON TRUE
ORDER BY top_parents.rrf_score DESC, child.chunk_id;
"""


def _database_url() -> str:
    """Return the PostgreSQL connection URL or fail before opening a connection."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL must be set to use the pgvector retrieval engine.")
    return database_url


def _psycopg() -> Any:
    """Load psycopg only when PostgreSQL access is requested."""
    try:
        import psycopg
    except ImportError as error:
        raise RuntimeError("Install PostgreSQL dependencies with: uv add 'psycopg[binary]>=3.2'") from error
    return psycopg


def _jsonb(value: object) -> Any:
    """Wrap JSON values using psycopg's JSONB adapter."""
    try:
        from psycopg.types.json import Jsonb
    except ImportError as error:
        raise RuntimeError("Install PostgreSQL dependencies with: uv add 'psycopg[binary]>=3.2'") from error
    return Jsonb(value)


def _vector_literal(values: list[float]) -> str:
    """Serialize one embedding for PostgreSQL's vector input format."""
    return "[" + ",".join(str(value) for value in values) + "]"


def _embed(texts: list[str]) -> list[list[float]]:
    """Generate 1,536-dimensional Gemini embeddings through the shared client."""
    if not texts:
        return []
    embeddings: list[list[float]] = []
    for offset in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        response = llm_client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=texts[offset : offset + EMBEDDING_BATCH_SIZE],
            dimensions=EMBEDDING_DIMENSION,
        )
        embeddings.extend(list(item.embedding) for item in response.data)
    if len(embeddings) != len(texts):
        raise RuntimeError("Gemini returned a different number of embeddings than requested.")
    if any(len(embedding) != EMBEDDING_DIMENSION for embedding in embeddings):
        raise RuntimeError(
            f"Gemini embedding dimension must be {EMBEDDING_DIMENSION}; "
            "update the schema and re-embed if the embedding model changes."
        )
    return embeddings


def _matched_table_text_for_reranking(table_chunks: list[dict[str, Any]]) -> str:
    """Return only the best table match so reranking input stays bounded."""
    return "\n\n".join(table_chunk["text_with_context"] for table_chunk in table_chunks)


def initialize_schema() -> None:
    """Create the pgvector extension, relational tables, and retrieval indexes."""
    psycopg = _psycopg()
    with psycopg.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
    logger.info("Initialized PostgreSQL pgvector retrieval schema")


def _required(bundle_json: dict[str, Any], key: str) -> Any:
    """Return a required bundle field with a clear contract error."""
    if key not in bundle_json:
        raise ValueError(f"Preprocessor bundle is missing required field: {key}")
    return bundle_json[key]


def document_ingestion_stats(document_id: str) -> dict[str, int] | None:
    """Return normalized-tier counts when a document is already present in PostgreSQL."""
    psycopg = _psycopg()
    with psycopg.connect(_database_url()) as connection:
        with connection.cursor(row_factory=psycopg.rows.dict_row) as cursor:
            cursor.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM parents WHERE doc_id = document.id) AS parents,
                    (SELECT COUNT(*) FROM figures WHERE doc_id = document.id) AS figures,
                    (SELECT COUNT(*) FROM tables WHERE doc_id = document.id) AS tables,
                    (SELECT COUNT(*) FROM table_chunks WHERE doc_id = document.id) AS table_chunks,
                    (SELECT COUNT(*) FROM children WHERE doc_id = document.id) AS children
                FROM documents AS document
                WHERE document.id = %s
                """,
                (document_id,),
            )
            row = cursor.fetchone()
    if row is None:
        return None
    return {key: int(value) for key, value in row.items()}


def ingest_bundle(bundle_json: dict) -> dict[str, int]:
    """Embed and atomically load one normalized preprocessor bundle into PostgreSQL.

    Existing records for the document are deleted and replaced inside the same
    transaction, preventing partially refreshed parent/child relationships.
    """
    document = _required(bundle_json, "document")
    document_id = document["document_id"]
    parents = _required(bundle_json, "parents")
    figures = _required(bundle_json, "figures")
    tables = _required(bundle_json, "tables")
    table_chunks = _required(bundle_json, "table_chunks")
    children = _required(bundle_json, "children")
    embeddings = _embed([child["text_with_context"] for child in children])

    psycopg = _psycopg()
    with psycopg.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM documents WHERE id = %s", (document_id,))
            cursor.execute(
                "INSERT INTO documents (id, source_path, summary) VALUES (%s, %s, %s)",
                (document_id, document["source_path"], document["summary"]),
            )
            cursor.executemany(
                """
                INSERT INTO parents (id, doc_id, parent_text, figure_ids, table_ids)
                VALUES (%s, %s, %s, %s, %s)
                """,
                [
                    (
                        parent["parent_id"],
                        document_id,
                        parent["parent_text"],
                        parent["figure_ids"],
                        parent["table_ids"],
                    )
                    for parent in parents
                ],
            )
            cursor.executemany(
                "INSERT INTO figures (id, doc_id, caption, bounding_boxes) VALUES (%s, %s, %s, %s)",
                [
                    (figure["figure_id"], document_id, figure["caption"], _jsonb(figure["bounding_boxes"]))
                    for figure in figures
                ],
            )
            cursor.executemany(
                """
                INSERT INTO tables (
                    id, doc_id, markdown, heading, caption, context, bounding_boxes,
                    row_count, column_count, chunk_ids
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        table["table_id"],
                        document_id,
                        table["markdown"],
                        table["heading"],
                        table["caption"],
                        table["context"],
                        _jsonb(table["bounding_boxes"]),
                        table["row_count"],
                        table["column_count"],
                        table["chunk_ids"],
                    )
                    for table in tables
                ],
            )
            cursor.executemany(
                """
                INSERT INTO table_chunks (
                    id, table_id, doc_id, row_start, row_end, text_with_context
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        table_chunk["table_chunk_id"],
                        table_chunk["table_id"],
                        document_id,
                        table_chunk["row_start"],
                        table_chunk["row_end"],
                        table_chunk["text_with_context"],
                    )
                    for table_chunk in table_chunks
                ],
            )
            cursor.executemany(
                """
                INSERT INTO children (id, parent_id, doc_id, text_with_context, embedding)
                VALUES (%s, %s, %s, %s, %s::vector)
                """,
                [
                    (
                        child["chunk_id"],
                        child["parent_id"],
                        document_id,
                        child["text_with_context"],
                        _vector_literal(embedding),
                    )
                    for child, embedding in zip(children, embeddings, strict=True)
                ],
            )
    logger.info(
        "Ingested normalized document bundle",
        extra={"document_id": document_id, "children": len(children), "tables": len(tables)},
    )
    return {
        "parents": len(parents),
        "figures": len(figures),
        "tables": len(tables),
        "table_chunks": len(table_chunks),
        "children": len(children),
    }


def attach_documents_to_session(user_id: str, session_id: str, document_ids: list[str]) -> None:
    """Attach existing normalized documents to one persistent chat session."""
    if not user_id.strip() or not session_id.strip():
        raise ValueError("user_id and session_id must not be empty")
    normalized_ids = list(dict.fromkeys(document_id for document_id in document_ids if document_id))
    if not normalized_ids:
        return

    psycopg = _psycopg()
    with psycopg.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM documents WHERE id = ANY(%s)", (normalized_ids,))
            existing_ids = {record[0] for record in cursor.fetchall()}
            missing_ids = set(normalized_ids) - existing_ids
            if missing_ids:
                raise ValueError("Cannot attach documents that have not been ingested")
            cursor.execute(
                """
                INSERT INTO user_sessions (user_id, session_id, document_ids)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id, session_id) DO UPDATE
                SET document_ids = ARRAY(
                        SELECT DISTINCT document_id
                        FROM unnest(user_sessions.document_ids || EXCLUDED.document_ids) AS document_id
                    ),
                    updated_at = NOW()
                """,
                (user_id, session_id, normalized_ids),
            )
    logger.info(
        "Attached documents to chat session",
        extra={"user_id": user_id, "session_id": session_id, "document_count": len(normalized_ids)},
    )


def _flashrank_rerank(query: str, records: list[dict[str, Any]], top_k: int) -> list[GroundedEvidence]:
    """Rerank parent evidence with FlashRank after the SQL retrieval pass."""
    try:
        from flashrank import Ranker, RerankRequest
    except ImportError as error:
        raise RuntimeError("Install reranking dependencies with: uv add 'flashrank>=0.2.10'") from error

    ranker = Ranker(model_name=os.getenv("RERANKER_MODEL_NAME", "ms-marco-MiniLM-L-12-v2"))
    passages = [
        {
            "id": str(index),
            "text": "\n\n".join(
                part
                for part in (
                    _matched_table_text_for_reranking(list(record["matched_table_chunks"])),
                    record["child_text"],
                    record["parent_text"],
                )
                if part
            ),
        }
        for index, record in enumerate(records)
    ]
    ranked = ranker.rerank(RerankRequest(query=query, passages=passages))
    evidence: list[GroundedEvidence] = []
    for result in ranked[:top_k]:
        record = records[int(result["id"])]
        evidence.append(
            {
                "chunk_id": record["chunk_id"],
                "child_text": record["child_text"],
                "parent_id": record["parent_id"],
                "parent_text": record["parent_text"],
                "document_id": record["document_id"],
                "rrf_score": float(record["rrf_score"]),
                "vector_distance": (
                    float(record["vector_distance"]) if record["vector_distance"] is not None else None
                ),
                "lexical_match": bool(record["lexical_match"]),
                "rrf_score_margin": float(record["rrf_score_margin"]),
                "reranker_score": float(result["score"]),
                "figures": list(record["figures"]),
                "tables": list(record["tables"]),
                "matched_table_chunks": list(record["matched_table_chunks"]),
            }
        )
    return evidence


def _assess_confidence(records: list[dict[str, Any]]) -> RetrievalConfidence:
    """Assess whether the strongest RRF candidate is grounded enough to answer."""
    if not records:
        return {
            "status": "not_found",
            "rrf_score": 0.0,
            "vector_distance": None,
            "lexical_match": False,
            "rrf_score_margin": 0.0,
            "reasons": ["No RRF candidates were returned."],
        }

    top_record = records[0]
    rrf_score = float(top_record["rrf_score"])
    vector_distance = (
        float(top_record["vector_distance"]) if top_record["vector_distance"] is not None else None
    )
    lexical_match = bool(top_record["lexical_match"])
    rrf_score_margin = float(top_record["rrf_score_margin"])
    reasons: list[str] = []

    if rrf_score < MIN_RRF_SCORE:
        reasons.append(f"RRF score {rrf_score:.5f} is below {MIN_RRF_SCORE:.5f}.")
    if vector_distance is None or vector_distance > MAX_VECTOR_DISTANCE:
        distance_text = "missing" if vector_distance is None else f"{vector_distance:.5f}"
        reasons.append(f"Vector distance {distance_text} is weaker than {MAX_VECTOR_DISTANCE:.5f}.")
    if rrf_score_margin < MIN_RRF_SCORE_MARGIN:
        reasons.append(
            f"RRF score margin {rrf_score_margin:.5f} is below {MIN_RRF_SCORE_MARGIN:.5f}."
        )

    if not lexical_match and reasons:
        return {
            "status": "not_found",
            "rrf_score": rrf_score,
            "vector_distance": vector_distance,
            "lexical_match": lexical_match,
            "rrf_score_margin": rrf_score_margin,
            "reasons": reasons + ["No lexical evidence matched the uploaded documents."],
        }
    if reasons:
        return {
            "status": "clarification_needed",
            "rrf_score": rrf_score,
            "vector_distance": vector_distance,
            "lexical_match": lexical_match,
            "rrf_score_margin": rrf_score_margin,
            "reasons": reasons,
        }
    return {
        "status": "grounded",
        "rrf_score": rrf_score,
        "vector_distance": vector_distance,
        "lexical_match": lexical_match,
        "rrf_score_margin": rrf_score_margin,
        "reasons": [],
    }


def hybrid_search_and_join(
    query: str,
    top_k: int = 5,
    include_ambiguous_evidence: bool = False,
    document_ids: list[str] | None = None,
) -> RetrievalResponse:
    """Run hybrid retrieval, optionally retaining ambiguous candidates for verification."""
    if not query.strip():
        raise ValueError("query must not be empty")
    if top_k < 1:
        raise ValueError("top_k must be at least 1")

    query_embedding = _embed([query])[0]
    candidate_limit = top_k * RRF_CANDIDATE_MULTIPLIER
    psycopg = _psycopg()
    with psycopg.connect(_database_url()) as connection:
        with connection.cursor(row_factory=psycopg.rows.dict_row) as cursor:
            cursor.execute(
                HYBRID_SEARCH_AND_JOIN_SQL,
                (
                    _vector_literal(query_embedding),
                    query,
                    document_ids or [],
                    candidate_limit,
                    candidate_limit,
                    candidate_limit,
                    RRF_K,
                    candidate_limit,
                ),
            )
            records = list(cursor.fetchall())
    confidence = _assess_confidence(records)
    if confidence["status"] == "not_found":
        logger.info("Retrieval declined due to insufficient evidence", extra={"confidence": confidence})
        return {
            "status": "not_found",
            "message": "Not found in uploaded documents.",
            "confidence": confidence,
            "evidence": [],
        }
    if confidence["status"] == "clarification_needed":
        logger.info("Retrieval needs clarification due to ambiguous evidence", extra={"confidence": confidence})
        return {
            "status": "clarification_needed",
            "message": "I found ambiguous evidence in the uploaded documents. Please clarify your question.",
            "confidence": confidence,
            "evidence": _flashrank_rerank(query, records, top_k) if include_ambiguous_evidence else [],
        }
    return {
        "status": "grounded",
        "message": "Grounded evidence retrieved.",
        "confidence": confidence,
        "evidence": _flashrank_rerank(query, records, top_k),
    }
