"""Static contract checks for the pgvector retrieval implementation."""

from retrieval.pg_engine import (
    EMBEDDING_DIMENSION,
    HYBRID_SEARCH_AND_JOIN_SQL,
    _matched_table_text_for_reranking,
    _vector_literal,
)


def test_schema_defines_hnsw_vector_and_full_text_indexes() -> None:
    """Keep the required pgvector and FTS indexes from regressing."""
    schema = open("retrieval/schema.sql", encoding="utf-8").read()

    assert "CREATE EXTENSION IF NOT EXISTS vector" in schema
    assert "embedding VECTOR(1536)" in schema
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
    assert HYBRID_SEARCH_AND_JOIN_SQL.count("%s") == 8


def test_vector_literal_uses_pgvector_input_format() -> None:
    """Serialize values in the format accepted by PostgreSQL's vector type."""
    assert _vector_literal([1.0, 2.5]) == "[1.0,2.5]"
    assert EMBEDDING_DIMENSION == 1536


def test_only_matching_table_rows_are_included_in_reranker_evidence() -> None:
    """Ensure table-only hits retain one bounded, matching row for reranking."""
    table_chunks = [{"text_with_context": "Temperature limit: 180°C"}]

    assert _matched_table_text_for_reranking(table_chunks) == "Temperature limit: 180°C"
