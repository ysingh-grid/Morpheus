"""Load normalized preprocessor bundles and retrieve grounded RAG evidence.

This module keeps vector search and relational context in PostgreSQL.  It uses a
single RRF CTE query to fuse child-vector and full-text ranks, then joins the
winning children to their parent blocks, figures, and tables atomically.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from pathlib import Path
from typing import Any, Callable, Literal, TypedDict

from langsmith import traceable

from core.config import llm_client

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL_NAME", "gemini-embedding-001")
EMBEDDING_DIMENSION = 1536
EMBEDDING_BATCH_SIZE = 100
RRF_K = 60
RRF_CANDIDATE_MULTIPLIER = 10
MIN_RRF_SCORE = float(os.getenv("RETRIEVAL_MIN_RRF_SCORE", "0.012"))
MAX_VECTOR_DISTANCE = float(os.getenv("RETRIEVAL_MAX_VECTOR_DISTANCE", "0.460"))
MIN_RRF_SCORE_MARGIN = float(os.getenv("RETRIEVAL_MIN_RRF_SCORE_MARGIN", "0.0"))
SCHEMA_PATH = Path(__file__).with_name("schema.sql")
ProgressCallback = Callable[[int, str, dict[str, Any]], None]


class GroundedEvidence(TypedDict):
    """One reranked child hit with its normalized source evidence."""

    chunk_id: str
    child_text: str
    parent_id: str
    parent_text: str
    document_id: str
    page_numbers: list[int]
    parent_page_numbers: list[int]
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
    policy: str
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
        MAX(ts_rank_cd(child.retrieval_fts_content, input.query_terms)) AS lexical_score
    FROM children AS child
    CROSS JOIN search_input AS input
    WHERE (cardinality(input.document_ids) = 0 OR child.doc_id = ANY(input.document_ids))
      AND child.retrieval_fts_content @@ input.query_terms
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
    child.page_numbers,
    parent.id AS parent_id,
    parent.parent_text,
    parent.page_numbers AS parent_page_numbers,
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
        source_child.text_with_context AS child_text,
        source_child.page_numbers
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
                'text_with_context', table_chunk.text_with_context,
                'page_numbers', table_chunk.page_numbers
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
            'text_with_context', matched_table_chunk.text_with_context,
            'page_numbers', matched_table_chunk.page_numbers
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
        raise RuntimeError(
            "DATABASE_URL must be set to use the pgvector retrieval engine."
        )
    return database_url


def _psycopg() -> Any:
    """Load psycopg only when PostgreSQL access is requested."""
    try:
        import psycopg
    except ImportError as error:
        raise RuntimeError(
            "Install PostgreSQL dependencies with: uv add 'psycopg[binary]>=3.2'"
        ) from error
    return psycopg


def _jsonb(value: object) -> Any:
    """Wrap JSON values using psycopg's JSONB adapter."""
    try:
        from psycopg.types.json import Jsonb
    except ImportError as error:
        raise RuntimeError(
            "Install PostgreSQL dependencies with: uv add 'psycopg[binary]>=3.2'"
        ) from error
    return Jsonb(value)


def _vector_literal(values: list[float]) -> str:
    """Serialize one embedding for PostgreSQL's vector input format."""
    return "[" + ",".join(str(value) for value in values) + "]"


def _embed(
    texts: list[str],
    progress_callback: ProgressCallback | None = None,
) -> list[list[float]]:
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
        if progress_callback is not None:
            completed = min(offset + EMBEDDING_BATCH_SIZE, len(texts))
            progress_callback(
                round(85 * completed / len(texts)),
                "embedding_children",
                {"completed": completed, "total": len(texts)},
            )
    if len(embeddings) != len(texts):
        raise RuntimeError(
            "Gemini returned a different number of embeddings than requested."
        )
    if any(len(embedding) != EMBEDDING_DIMENSION for embedding in embeddings):
        raise RuntimeError(
            f"Gemini embedding dimension must be {EMBEDDING_DIMENSION}; "
            "update the schema and re-embed if the embedding model changes."
        )
    return embeddings


def _matched_table_text_for_reranking(table_chunks: list[dict[str, Any]]) -> str:
    """Return only the best table match so reranking input stays bounded."""
    return "\n\n".join(table_chunk["text_with_context"] for table_chunk in table_chunks)


def _child_retrieval_text(text_with_context: str) -> str:
    """Remove the repeated global summary from text used for indexing and ranking."""
    if not text_with_context.startswith("Document summary:"):
        return text_with_context
    _, separator, child_text = text_with_context.partition("\n\n")
    return child_text if separator else text_with_context


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


@traceable(name="get_full_table", run_type="tool")
def get_full_table(doc_id: str, table_id: str) -> dict[str, Any] | None:
    """Retrieve full normalized table content and metadata by document and table ID."""
    if not doc_id.strip() or not table_id.strip():
        raise ValueError("doc_id and table_id must not be empty.")
    psycopg = _psycopg()
    with psycopg.connect(_database_url()) as connection:
        with connection.cursor(row_factory=psycopg.rows.dict_row) as cursor:
            cursor.execute(
                """
                SELECT markdown, heading, caption, context, row_count, column_count
                FROM tables
                WHERE doc_id = %s AND id = %s
                """,
                (doc_id, table_id),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return {
                "doc_id": doc_id,
                "table_id": table_id,
                "markdown": str(row["markdown"]),
                "heading": str(row["heading"]),
                "caption": str(row["caption"]),
                "context": str(row["context"]),
                "row_count": int(row["row_count"]),
                "column_count": int(row["column_count"]),
            }


def _file_sha256(file_path: Path) -> str:
    """Hash a local document without loading the complete file into memory."""
    digest = hashlib.sha256()
    with file_path.open("rb") as source_file:
        for block in iter(lambda: source_file.read(1_048_576), b""):
            digest.update(block)
    return digest.hexdigest()


def consolidate_document_identity(
    file_path: str | Path,
    preferred_document_id: str | None = None,
) -> dict[str, Any]:
    """Merge legacy filename-derived copies into one content-addressed document.

    The most recently attached candidate is retained unless an explicit preferred
    identifier is supplied. Normalized rows and embeddings are copied locally;
    this operation never calls an embedding or language-model API.
    """
    source_file = Path(file_path).resolve()
    if not source_file.is_file():
        raise ValueError(f"Document does not exist or is not a file: {file_path}")
    content_sha256 = _file_sha256(source_file)
    canonical_id = f"sha256-{content_sha256}"
    legacy_suffix = f"-{content_sha256[:16]}"
    psycopg = _psycopg()

    with psycopg.connect(_database_url()) as connection:
        with connection.cursor(row_factory=psycopg.rows.dict_row) as cursor:
            cursor.execute(
                """
                SELECT id, source_path
                FROM documents
                WHERE id = %s
                   OR content_sha256 = %s
                   OR id LIKE %s
                """,
                (canonical_id, content_sha256, f"%{legacy_suffix}"),
            )
            candidates = list(cursor.fetchall())
            candidate_ids = {str(candidate["id"]) for candidate in candidates}

            cursor.execute("SELECT id, source_path FROM documents")
            for candidate in cursor.fetchall():
                candidate_id = str(candidate["id"])
                if candidate_id in candidate_ids:
                    continue
                candidate_path = Path(str(candidate["source_path"]))
                if not candidate_path.is_absolute():
                    candidate_path = Path.cwd() / candidate_path
                try:
                    matches_content = (
                        candidate_path.is_file()
                        and _file_sha256(candidate_path) == content_sha256
                    )
                except OSError:
                    matches_content = False
                if matches_content:
                    candidates.append(candidate)
                    candidate_ids.add(candidate_id)

            if not candidates:
                return {
                    "canonical_document_id": canonical_id,
                    "merged_document_ids": [],
                    "status": "not_ingested",
                }

            if preferred_document_id is not None and preferred_document_id not in candidate_ids:
                raise ValueError("Preferred document is not a matching ingested copy")

            cursor.execute(
                """
                SELECT
                    document.id,
                    MAX(session.updated_at) AS last_attached,
                    (SELECT COUNT(*) FROM children WHERE doc_id = document.id) AS child_count,
                    (SELECT COUNT(*) FROM figures WHERE doc_id = document.id) AS figure_count,
                    (SELECT COUNT(*) FROM tables WHERE doc_id = document.id) AS table_count
                FROM documents AS document
                LEFT JOIN user_sessions AS session
                  ON document.id = ANY(session.document_ids)
                WHERE document.id = ANY(%s)
                GROUP BY document.id
                ORDER BY
                    (document.id = %s) DESC,
                    MAX(session.updated_at) DESC NULLS LAST,
                    child_count DESC,
                    figure_count DESC,
                    table_count DESC,
                    document.id
                """,
                (list(candidate_ids), preferred_document_id or ""),
            )
            retained_id = str(cursor.fetchone()["id"])

            if retained_id != canonical_id:
                cursor.execute("DELETE FROM documents WHERE id = %s", (canonical_id,))
                cursor.execute(
                    """
                    INSERT INTO documents (id, content_sha256, source_path, summary)
                    SELECT %s, %s, source_path, summary
                    FROM documents
                    WHERE id = %s
                    """,
                    (canonical_id, content_sha256, retained_id),
                )

                cursor.execute(
                    """
                    SELECT id, parent_text, page_numbers, figure_ids, table_ids
                    FROM parents WHERE doc_id = %s ORDER BY id
                    """,
                    (retained_id,),
                )
                source_parents = list(cursor.fetchall())
                parent_id_map = {
                    str(parent["id"]): f"{canonical_id}-parent-{index}"
                    for index, parent in enumerate(source_parents)
                }
                cursor.executemany(
                    """
                    INSERT INTO parents (
                        id, doc_id, parent_text, page_numbers, figure_ids, table_ids
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            parent_id_map[str(parent["id"])],
                            canonical_id,
                            parent["parent_text"],
                            parent["page_numbers"],
                            parent["figure_ids"],
                            parent["table_ids"],
                        )
                        for parent in source_parents
                    ],
                )
                cursor.execute(
                    """
                    INSERT INTO figures (id, doc_id, caption, bounding_boxes)
                    SELECT id, %s, caption, bounding_boxes
                    FROM figures WHERE doc_id = %s
                    """,
                    (canonical_id, retained_id),
                )
                cursor.execute(
                    """
                    INSERT INTO tables (
                        id, doc_id, markdown, heading, caption, context,
                        bounding_boxes, row_count, column_count, chunk_ids
                    )
                    SELECT
                        id, %s, markdown, heading, caption, context,
                        bounding_boxes, row_count, column_count, chunk_ids
                    FROM tables WHERE doc_id = %s
                    """,
                    (canonical_id, retained_id),
                )
                cursor.execute(
                    """
                    INSERT INTO table_chunks (
                        id, table_id, doc_id, row_start, row_end,
                        text_with_context, page_numbers
                    )
                    SELECT
                        id, table_id, %s, row_start, row_end,
                        text_with_context, page_numbers
                    FROM table_chunks WHERE doc_id = %s
                    """,
                    (canonical_id, retained_id),
                )
                cursor.execute(
                    """
                    SELECT id, parent_id, text_with_context, retrieval_text,
                           page_numbers, embedding::text AS embedding
                    FROM children WHERE doc_id = %s ORDER BY id
                    """,
                    (retained_id,),
                )
                source_children = list(cursor.fetchall())
                cursor.executemany(
                    """
                    INSERT INTO children (
                        id, parent_id, doc_id, text_with_context, retrieval_text,
                        page_numbers, embedding
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s::vector)
                    """,
                    [
                        (
                            f"{canonical_id}-child-{index}",
                            parent_id_map[str(child["parent_id"])],
                            canonical_id,
                            child["text_with_context"],
                            child["retrieval_text"],
                            child["page_numbers"],
                            child["embedding"],
                        )
                        for index, child in enumerate(source_children)
                    ],
                )
            else:
                cursor.execute(
                    "UPDATE documents SET content_sha256 = %s WHERE id = %s",
                    (content_sha256, canonical_id),
                )

            cursor.execute(
                """
                SELECT user_id, session_id, document_ids
                FROM user_sessions
                WHERE document_ids && %s
                """,
                (list(candidate_ids),),
            )
            session_updates = []
            for session in cursor.fetchall():
                updated_ids: list[str] = []
                for document_id in session["document_ids"]:
                    replacement = canonical_id if document_id in candidate_ids else document_id
                    if replacement not in updated_ids:
                        updated_ids.append(replacement)
                session_updates.append(
                    (updated_ids, session["user_id"], session["session_id"])
                )
            cursor.executemany(
                """
                UPDATE user_sessions SET document_ids = %s, updated_at = NOW()
                WHERE user_id = %s AND session_id = %s
                """,
                session_updates,
            )
            merged_ids = sorted(candidate_ids - {canonical_id})
            if merged_ids:
                cursor.execute("DELETE FROM documents WHERE id = ANY(%s)", (merged_ids,))

    logger.info(
        "Consolidated content-identical document records",
        extra={
            "canonical_document_id": canonical_id,
            "merged_document_count": len(merged_ids),
        },
    )
    return {
        "canonical_document_id": canonical_id,
        "merged_document_ids": merged_ids,
        "retained_source_document_id": retained_id,
        "status": "consolidated",
    }


@traceable(name="ingest_bundle", run_type="tool")
def ingest_bundle(
    bundle_json: dict[str, Any],
    progress_callback: ProgressCallback | None = None,
    embeddings: list[list[float]] | None = None,
) -> dict[str, int]:
    """Embed and atomically load one normalized preprocessor bundle into PostgreSQL.

    Existing records for the document are deleted and replaced inside the same
    transaction, preventing partially refreshed parent/child relationships.
    """
    document = _required(bundle_json, "document")
    document_id = document["document_id"]
    content_sha256 = document.get("content_sha256")
    if not content_sha256 and document_id.startswith("sha256-"):
        content_sha256 = document_id.removeprefix("sha256-")
    parents = _required(bundle_json, "parents")
    figures = _required(bundle_json, "figures")
    tables = _required(bundle_json, "tables")
    table_chunks = _required(bundle_json, "table_chunks")
    children = _required(bundle_json, "children")
    if progress_callback is not None:
        progress_callback(0, "starting_vector_storage", {"total": len(children)})
    retrieval_texts = [
        _child_retrieval_text(child["text_with_context"]) for child in children
    ]
    if embeddings is None:
        embeddings = _embed(retrieval_texts, progress_callback)
    elif len(embeddings) != len(retrieval_texts):
        raise ValueError("One embedding is required for every child chunk.")
    elif any(len(embedding) != EMBEDDING_DIMENSION for embedding in embeddings):
        raise ValueError(
            f"Gemini embedding dimension must be {EMBEDDING_DIMENSION}; "
            "update the schema and re-embed if the embedding model changes."
        )

    psycopg = _psycopg()
    if progress_callback is not None:
        progress_callback(90, "writing_postgresql", {"total": len(children)})
    with psycopg.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM documents WHERE id = %s", (document_id,))
            cursor.execute(
                """
                INSERT INTO documents (id, content_sha256, source_path, summary)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    document_id,
                    content_sha256,
                    document["source_path"],
                    document["summary"],
                ),
            )
            cursor.executemany(
                """
                INSERT INTO parents (id, doc_id, parent_text, page_numbers, figure_ids, table_ids)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        parent["parent_id"],
                        document_id,
                        parent["parent_text"],
                        parent.get("page_numbers", []),
                        parent["figure_ids"],
                        parent["table_ids"],
                    )
                    for parent in parents
                ],
            )
            cursor.executemany(
                "INSERT INTO figures (id, doc_id, caption, bounding_boxes) VALUES (%s, %s, %s, %s)",
                [
                    (
                        figure["figure_id"],
                        document_id,
                        figure["caption"],
                        _jsonb(figure["bounding_boxes"]),
                    )
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
                    id, table_id, doc_id, row_start, row_end, text_with_context, page_numbers
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        table_chunk["table_chunk_id"],
                        table_chunk["table_id"],
                        document_id,
                        table_chunk["row_start"],
                        table_chunk["row_end"],
                        table_chunk["text_with_context"],
                        table_chunk.get("page_numbers", []),
                    )
                    for table_chunk in table_chunks
                ],
            )
            cursor.executemany(
                """
                INSERT INTO children (
                    id, parent_id, doc_id, text_with_context, retrieval_text,
                    page_numbers, embedding
                ) VALUES (%s, %s, %s, %s, %s, %s, %s::vector)
                """,
                [
                    (
                        child["chunk_id"],
                        child["parent_id"],
                        document_id,
                        child["text_with_context"],
                        retrieval_text,
                        child.get("metadata", {}).get("page_numbers", []),
                        _vector_literal(embedding),
                    )
                    for child, retrieval_text, embedding in zip(
                        children, retrieval_texts, embeddings, strict=True
                    )
                ],
            )
    if progress_callback is not None:
        progress_callback(100, "vector_storage_complete", {"total": len(children)})
    logger.info(
        "Ingested normalized document bundle",
        extra={
            "document_id": document_id,
            "children": len(children),
            "tables": len(tables),
        },
    )
    return {
        "parents": len(parents),
        "figures": len(figures),
        "tables": len(tables),
        "table_chunks": len(table_chunks),
        "children": len(children),
    }


@traceable(name="reindex_child_embeddings", run_type="tool")
def reindex_child_embeddings(
    document_ids: list[str], progress_callback: ProgressCallback | None = None
) -> int:
    """Rebuild existing child embeddings from page-local retrieval text."""
    normalized_ids = list(dict.fromkeys(item for item in document_ids if item))
    if not normalized_ids:
        return 0
    psycopg = _psycopg()
    with psycopg.connect(_database_url()) as connection:
        with connection.cursor(row_factory=psycopg.rows.dict_row) as cursor:
            cursor.execute(
                """
                SELECT id, retrieval_text
                FROM children
                WHERE doc_id = ANY(%s)
                ORDER BY doc_id, id
                """,
                (normalized_ids,),
            )
            records = list(cursor.fetchall())
    if not records:
        return 0
    embeddings = _embed(
        [str(record["retrieval_text"]) for record in records], progress_callback
    )
    with psycopg.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.executemany(
                "UPDATE children SET embedding = %s::vector WHERE id = %s",
                [
                    (_vector_literal(embedding), record["id"])
                    for record, embedding in zip(records, embeddings, strict=True)
                ],
            )
    logger.info(
        "Reindexed child embeddings from retrieval text",
        extra={"document_count": len(normalized_ids), "children": len(records)},
    )
    return len(records)


def fetch_reindexable_child_batch(
    batch_size: int, cursor_id: str | None = None
) -> list[dict[str, str]]:
    """Load one stable ID-ordered child slice for a resumable embedding rebuild."""
    if batch_size < 1 or batch_size > 1_000:
        raise ValueError("batch_size must be between 1 and 1000.")
    normalized_cursor = cursor_id.strip() if cursor_id else ""
    psycopg = _psycopg()
    with psycopg.connect(_database_url()) as connection:
        with connection.cursor(row_factory=psycopg.rows.dict_row) as cursor:
            cursor.execute(
                """
                SELECT id, retrieval_text
                FROM children
                WHERE id > %s
                ORDER BY id
                LIMIT %s
                """,
                (normalized_cursor, batch_size),
            )
            return [
                {"id": str(record["id"]), "retrieval_text": str(record["retrieval_text"])}
                for record in cursor.fetchall()
            ]


def count_reindexable_children() -> int:
    """Return the number of child rows included in a full embedding rebuild."""
    psycopg = _psycopg()
    with psycopg.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM children")
            row = cursor.fetchone()
    return int(row[0]) if row else 0


def reindex_child_embedding_batch(
    chunks: list[dict[str, str]], progress_callback: ProgressCallback | None = None
) -> str:
    """Atomically replace embeddings for one ID-ordered, retry-safe child batch."""
    if not chunks:
        raise ValueError("Cannot reindex an empty child batch.")
    chunk_ids = [chunk.get("id", "") for chunk in chunks]
    retrieval_texts = [chunk.get("retrieval_text", "") for chunk in chunks]
    if (
        any(not isinstance(chunk_id, str) or not chunk_id for chunk_id in chunk_ids)
        or any(not isinstance(text, str) or not text for text in retrieval_texts)
        or len(set(chunk_ids)) != len(chunk_ids)
        or chunk_ids != sorted(chunk_ids)
    ):
        raise ValueError("Reindex batches require unique ID-ordered chunks with retrieval text.")
    embeddings = _embed(retrieval_texts, progress_callback)
    psycopg = _psycopg()
    with psycopg.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.executemany(
                "UPDATE children SET embedding = %s::vector WHERE id = %s",
                [
                    (_vector_literal(embedding), chunk_id)
                    for chunk_id, embedding in zip(chunk_ids, embeddings, strict=True)
                ],
            )
    logger.info("Reindexed child embedding batch", extra={"children": len(chunks)})
    return chunk_ids[-1]


def attach_documents_to_session(
    user_id: str, session_id: str, document_ids: list[str]
) -> None:
    """Attach existing normalized documents to one persistent chat session."""
    if not user_id.strip() or not session_id.strip():
        raise ValueError("user_id and session_id must not be empty")
    normalized_ids = list(
        dict.fromkeys(document_id for document_id in document_ids if document_id)
    )
    if not normalized_ids:
        return

    psycopg = _psycopg()
    with psycopg.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM documents WHERE id = ANY(%s)", (normalized_ids,)
            )
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
        extra={
            "user_id": user_id,
            "session_id": session_id,
            "document_count": len(normalized_ids),
        },
    )


@traceable(name="flashrank_rerank", run_type="tool")
def _flashrank_rerank(
    query: str, records: list[dict[str, Any]], top_k: int
) -> list[GroundedEvidence]:
    """Rerank parent evidence with FlashRank after the SQL retrieval pass."""
    try:
        from flashrank import Ranker, RerankRequest
    except ImportError as error:
        raise RuntimeError(
            "Install reranking dependencies with: uv add 'flashrank>=0.2.10'"
        ) from error

    ranker = Ranker(
        model_name=os.getenv("RERANKER_MODEL_NAME", "ms-marco-MiniLM-L-12-v2")
    )
    passages = [
        {
            "id": str(index),
            "text": "\n\n".join(
                part
                for part in (
                    _matched_table_text_for_reranking(
                        list(record["matched_table_chunks"])
                    ),
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
                "page_numbers": list(record["page_numbers"]),
                "parent_page_numbers": list(record["parent_page_numbers"]),
                "rrf_score": float(record["rrf_score"]),
                "vector_distance": (
                    float(record["vector_distance"])
                    if record["vector_distance"] is not None
                    else None
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


def _record_matches_policy(
    record: dict[str, Any],
    policy: str,
    requested_page: int | None,
    requested_figure: int | None,
) -> bool:
    """Return whether a candidate contains the structural evidence an intent requires."""
    if policy == "table":
        return bool(record.get("matched_table_chunks") or record.get("tables"))
    if policy == "figure":
        if not record.get("figures"):
            return False
        if requested_figure is None:
            return True
        searchable_text = "\n".join(
            [
                str(record.get("child_text", "")),
                str(record.get("parent_text", "")),
                *(str(figure.get("caption", "")) for figure in record.get("figures", [])),
            ]
        )
        return bool(
            re.search(
                rf"\b(?:figure|fig\.?)\s*{requested_figure}\b",
                searchable_text,
                re.IGNORECASE,
            )
        )
    if policy == "page" and requested_page is not None:
        pages = {*record.get("page_numbers", []), *record.get("parent_page_numbers", [])}
        return requested_page in pages
    return True


def _prioritize_policy_records(
    query: str, records: list[dict[str, Any]], policy: str
) -> tuple[list[dict[str, Any]], int | None, int | None]:
    """Move the strongest structurally matching candidate ahead of generic matches."""
    page_match = re.search(r"\bpage\s+(\d+)\b", query, re.IGNORECASE)
    requested_page = int(page_match.group(1)) if page_match else None
    figure_match = re.search(
        r"\b(?:figure|fig\.?)\s*(\d+)\b", query, re.IGNORECASE
    )
    requested_figure = int(figure_match.group(1)) if figure_match else None
    if policy not in {"table", "figure", "page"}:
        return records, requested_page, requested_figure
    matching = [
        record
        for record in records
        if _record_matches_policy(record, policy, requested_page, requested_figure)
    ]
    nonmatching = [record for record in records if record not in matching]
    return [*matching, *nonmatching], requested_page, requested_figure


@traceable(name="assess_confidence", run_type="tool")
def _assess_confidence(
    records: list[dict[str, Any]],
    policy: str = "semantic",
    requested_page: int | None = None,
    requested_figure: int | None = None,
) -> RetrievalConfidence:
    """Assess whether the strongest RRF candidate is grounded enough to answer."""
    if not records:
        return {
            "status": "not_found",
            "rrf_score": 0.0,
            "vector_distance": None,
            "lexical_match": False,
            "rrf_score_margin": 0.0,
            "policy": policy,
            "reasons": ["No RRF candidates were returned."],
        }

    top_record = records[0]
    rrf_score = float(top_record["rrf_score"])
    vector_distance = (
        float(top_record["vector_distance"])
        if top_record["vector_distance"] is not None
        else None
    )
    lexical_match = bool(top_record["lexical_match"])
    rrf_score_margin = float(top_record["rrf_score_margin"])
    reasons: list[str] = []

    structural_match = _record_matches_policy(
        top_record, policy, requested_page, requested_figure
    )
    if policy in {"table", "figure", "page"}:
        if not structural_match:
            return {
                "status": "not_found",
                "rrf_score": rrf_score,
                "vector_distance": vector_distance,
                "lexical_match": lexical_match,
                "rrf_score_margin": rrf_score_margin,
                "policy": policy,
                "reasons": [f"No {policy}-specific evidence matched the request."],
            }
        if lexical_match or (
            vector_distance is not None and vector_distance <= 0.50
        ):
            return {
                "status": "grounded",
                "rrf_score": rrf_score,
                "vector_distance": vector_distance,
                "lexical_match": lexical_match,
                "rrf_score_margin": rrf_score_margin,
                "policy": policy,
                "reasons": [],
            }

    if rrf_score < MIN_RRF_SCORE:
        reasons.append(f"RRF score {rrf_score:.5f} is below {MIN_RRF_SCORE:.5f}.")
    if vector_distance is None or vector_distance > MAX_VECTOR_DISTANCE:
        distance_text = (
            "missing" if vector_distance is None else f"{vector_distance:.5f}"
        )
        reasons.append(
            f"Vector distance {distance_text} is weaker than {MAX_VECTOR_DISTANCE:.5f}."
        )
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
            "policy": policy,
            "reasons": reasons
            + ["No lexical evidence matched the uploaded documents."],
        }
    if reasons:
        return {
            "status": "clarification_needed",
            "rrf_score": rrf_score,
            "vector_distance": vector_distance,
            "lexical_match": lexical_match,
            "rrf_score_margin": rrf_score_margin,
            "policy": policy,
            "reasons": reasons,
        }
    return {
        "status": "grounded",
        "rrf_score": rrf_score,
        "vector_distance": vector_distance,
        "lexical_match": lexical_match,
        "rrf_score_margin": rrf_score_margin,
        "policy": policy,
        "reasons": [],
    }


@traceable(name="hybrid_search_and_join", run_type="retriever")
def hybrid_search_and_join(
    query: str,
    top_k: int = 5,
    include_ambiguous_evidence: bool = False,
    document_ids: list[str] | None = None,
    confidence_policy: str = "semantic",
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
    records, requested_page, requested_figure = _prioritize_policy_records(
        query, records, confidence_policy
    )
    confidence = _assess_confidence(
        records, confidence_policy, requested_page, requested_figure
    )
    if confidence["status"] == "not_found":
        logger.info(
            "Retrieval declined due to insufficient evidence",
            extra={"confidence": confidence},
        )
        return {
            "status": "not_found",
            "message": "Not found in uploaded documents.",
            "confidence": confidence,
            "evidence": [],
        }
    if confidence["status"] == "clarification_needed":
        logger.info(
            "Retrieval needs clarification due to ambiguous evidence",
            extra={"confidence": confidence},
        )
        return {
            "status": "clarification_needed",
            "message": "I found ambiguous evidence in the uploaded documents. Please clarify your question.",
            "confidence": confidence,
            "evidence": _flashrank_rerank(query, records, top_k)
            if include_ambiguous_evidence
            else [],
        }
    return {
        "status": "grounded",
        "message": "Grounded evidence retrieved.",
        "confidence": confidence,
        "evidence": _flashrank_rerank(query, records, top_k),
    }


@traceable(name="document_overview_and_join", run_type="retriever")
def document_overview_and_join(
    document_ids: list[str], top_k: int = 2
) -> RetrievalResponse:
    """Load stored summaries and opening parents without applying semantic rank gates."""
    if not document_ids:
        return {
            "status": "not_found",
            "message": "No documents are attached to this chat.",
            "confidence": {
                "status": "not_found",
                "rrf_score": 0.0,
                "vector_distance": None,
                "lexical_match": False,
                "rrf_score_margin": 0.0,
                "reasons": ["No attached document IDs were supplied."],
            },
            "evidence": [],
        }
    if top_k < 1:
        raise ValueError("top_k must be at least 1")

    psycopg = _psycopg()
    with psycopg.connect(_database_url()) as connection:
        with connection.cursor(row_factory=psycopg.rows.dict_row) as cursor:
            cursor.execute(
                """
                WITH opening_parents AS (
                    SELECT
                        parent.*,
                        ROW_NUMBER() OVER (
                            PARTITION BY parent.doc_id
                            ORDER BY
                                COALESCE(parent.page_numbers[1], 2147483647),
                                parent.id
                        ) AS opening_rank
                    FROM parents AS parent
                    WHERE parent.doc_id = ANY(%s)
                )
                SELECT
                    document.id AS document_id,
                    document.summary AS document_summary,
                    parent.id AS parent_id,
                    parent.parent_text,
                    parent.page_numbers AS parent_page_numbers,
                    child.id AS chunk_id,
                    child.text_with_context AS child_text,
                    child.page_numbers
                FROM documents AS document
                JOIN opening_parents AS parent
                  ON parent.doc_id = document.id
                 AND parent.opening_rank <= 2
                JOIN LATERAL (
                    SELECT source_child.id, source_child.text_with_context,
                           source_child.page_numbers
                    FROM children AS source_child
                    WHERE source_child.parent_id = parent.id
                    ORDER BY
                        COALESCE(source_child.page_numbers[1], 2147483647),
                        source_child.id
                    LIMIT 1
                ) AS child ON TRUE
                WHERE document.id = ANY(%s)
                ORDER BY document.id, parent.opening_rank
                LIMIT %s
                """,
                (document_ids, document_ids, top_k),
            )
            records = list(cursor.fetchall())

    if not records:
        return {
            "status": "not_found",
            "message": "The attached documents have no indexed opening content.",
            "confidence": {
                "status": "not_found",
                "rrf_score": 0.0,
                "vector_distance": None,
                "lexical_match": False,
                "rrf_score_margin": 0.0,
                "reasons": ["No opening parent and child records were available."],
            },
            "evidence": [],
        }

    evidence: list[GroundedEvidence] = [
        {
            "chunk_id": str(record["chunk_id"]),
            "child_text": str(record["child_text"]),
            "parent_id": str(record["parent_id"]),
            "parent_text": str(record["parent_text"]),
            "document_id": str(record["document_id"]),
            "page_numbers": list(record["page_numbers"] or []),
            "parent_page_numbers": list(record["parent_page_numbers"] or []),
            "rrf_score": 1.0,
            "vector_distance": 0.0,
            "lexical_match": True,
            "rrf_score_margin": 1.0,
            "reranker_score": 1.0,
            "figures": [],
            "tables": [],
            "matched_table_chunks": [],
        }
        for record in records
    ]
    return {
        "status": "grounded",
        "message": "Stored document overview and opening evidence loaded.",
        "confidence": {
            "status": "grounded",
            "rrf_score": 1.0,
            "vector_distance": 0.0,
            "lexical_match": True,
            "rrf_score_margin": 1.0,
            "reasons": [],
        },
        "evidence": evidence,
    }
