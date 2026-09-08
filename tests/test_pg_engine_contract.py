"""Static contract checks for the pgvector retrieval implementation."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from retrieval.pg_engine import (
    EMBEDDING_DIMENSION,
    HYBRID_SEARCH_AND_JOIN_SQL,
    _embed,
    _matched_table_text_for_reranking,
    _vector_literal,
    get_document_source_path,
    get_full_table,
)


def test_schema_defines_hnsw_vector_and_full_text_indexes() -> None:
    """Keep the required pgvector and FTS indexes from regressing."""
    schema = open("retrieval/schema.sql", encoding="utf-8").read()

    assert "CREATE EXTENSION IF NOT EXISTS vector" in schema
    assert "embedding VECTOR(1536)" in schema
    assert schema.count("page_numbers INTEGER[]") >= 3
    assert "USING hnsw (embedding vector_cosine_ops)" in schema
    assert "USING gin (fts_content)" in schema
    assert "table_chunks_fts_content_gin_idx" in schema


def test_hybrid_query_fuses_and_joins_in_one_sql_statement() -> None:
    """Require RRF CTEs and relational joins in the one retrieval query."""
    assert "vector_ranked AS" in HYBRID_SEARCH_AND_JOIN_SQL
    assert "child_fts_ranked AS" in HYBRID_SEARCH_AND_JOIN_SQL
    assert "table_fts_ranked AS" in HYBRID_SEARCH_AND_JOIN_SQL
    assert "rrf_scores AS" in HYBRID_SEARCH_AND_JOIN_SQL
    assert "websearch_to_tsquery('english', %s)" in HYBRID_SEARCH_AND_JOIN_SQL
    assert "JOIN parents AS parent" in HYBRID_SEARCH_AND_JOIN_SQL
    assert "FROM figures AS figure" in HYBRID_SEARCH_AND_JOIN_SQL
    assert "FROM tables AS source_table" in HYBRID_SEARCH_AND_JOIN_SQL
    assert "%s::text[] AS document_ids" in HYBRID_SEARCH_AND_JOIN_SQL
    assert "child.doc_id = ANY(input.document_ids)" in HYBRID_SEARCH_AND_JOIN_SQL
    assert "child.page_numbers" in HYBRID_SEARCH_AND_JOIN_SQL
    assert "parent.page_numbers AS parent_page_numbers" in HYBRID_SEARCH_AND_JOIN_SQL
    assert HYBRID_SEARCH_AND_JOIN_SQL.count("%s") == 8


def test_vector_literal_uses_pgvector_input_format() -> None:
    """Serialize values in the format accepted by PostgreSQL's vector type."""
    assert _vector_literal([1.0, 2.5]) == "[1.0,2.5]"
    assert EMBEDDING_DIMENSION == 1536


def test_only_matching_table_rows_are_included_in_reranker_evidence() -> None:
    """Ensure table-only hits retain one bounded, matching row for reranking."""
    table_chunks = [{"text_with_context": "Temperature limit: 180°C"}]

    assert _matched_table_text_for_reranking(table_chunks) == "Temperature limit: 180°C"


def test_embedding_batches_report_completed_child_counts() -> None:
    """Large bundle embedding reports actual completed batches rather than elapsed time."""
    embedding = [0.0] * EMBEDDING_DIMENSION
    responses = [
        SimpleNamespace(
            data=[SimpleNamespace(embedding=embedding) for _ in range(100)]
        ),
        SimpleNamespace(data=[SimpleNamespace(embedding=embedding)]),
    ]
    events: list[tuple[int, str, dict[str, int]]] = []

    with patch(
        "retrieval.pg_engine.llm_client.embeddings.create", side_effect=responses
    ):
        result = _embed(
            [f"child {index}" for index in range(101)],
            lambda percent, stage, details: events.append((percent, stage, details)),
        )

    assert len(result) == 101
    assert events[-1] == (85, "embedding_children", {"completed": 101, "total": 101})


def test_get_full_table_queries_by_composite_key() -> None:
    """Ensure get_full_table executes an index lookup by doc_id and table_id."""
    cursor = MagicMock()
    cursor.fetchone.return_value = {
        "markdown": "| Metric | 2024 |\n| --- | --- |\n| Total Assets | $110B |",
        "heading": "Table 1",
        "caption": "Summary of assets",
        "context": "Financial section",
        "row_count": 2,
        "column_count": 2,
    }
    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    psycopg = MagicMock()
    psycopg.connect.return_value.__enter__.return_value = connection

    with patch("retrieval.pg_engine._psycopg", return_value=psycopg):
        result = get_full_table("doc-123", "table-456")

    assert result == {
        "doc_id": "doc-123",
        "table_id": "table-456",
        "markdown": "| Metric | 2024 |\n| --- | --- |\n| Total Assets | $110B |",
        "heading": "Table 1",
        "caption": "Summary of assets",
        "context": "Financial section",
        "row_count": 2,
        "column_count": 2,
    }
    statement, params = cursor.execute.call_args.args
    assert "FROM tables" in statement
    assert "WHERE doc_id = %s AND id = %s" in statement
    assert params == ("doc-123", "table-456")


def test_get_document_source_path_resolves_existing_file(tmp_path: Path) -> None:
    """Document source path resolves to a valid Path object when the file exists."""
    doc_file = tmp_path / "test.pdf"
    doc_file.write_bytes(b"%PDF-1.7 data")
    cursor = MagicMock()
    cursor.fetchone.return_value = (str(doc_file),)
    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    psycopg = MagicMock()
    psycopg.connect.return_value.__enter__.return_value = connection

    with patch("retrieval.pg_engine._psycopg", return_value=psycopg):
        resolved = get_document_source_path("doc-123")

    assert resolved == doc_file
    assert resolved.is_file()


