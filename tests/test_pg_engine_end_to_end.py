"""Real PostgreSQL and Gemini integration coverage for two-tier retrieval.

Run with ``uv run --env-file .env python -m pytest -s -o log_cli=true
--log-cli-level=INFO tests/test_pg_engine_end_to_end.py``.  This test deliberately
uses the configured PostgreSQL database, Gemini embeddings, and FlashRank; it
does not mock any service.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

import psycopg

from retrieval.pg_engine import _database_url, hybrid_search_and_join, ingest_bundle, initialize_schema

logger = logging.getLogger(__name__)


def _bundle(document_id: str) -> dict[str, Any]:
    """Build one minimal normalized bundle that exercises every retrieval tier."""
    parent_id = f"{document_id}-parent-001"
    unrelated_parent_id = f"{document_id}-parent-002"
    table_id = f"{document_id}-table-001"
    figure_id = f"{document_id}-figure-001"
    table_chunk_id = f"{table_id}-rows-001-002"
    return {
        "document": {
            "document_id": document_id,
            "source_path": "tests/fixtures/two-tier-retrieval.pdf",
            "summary": "Quarterly revenue growth report with regional performance details.",
        },
        "parents": [
            {
                "parent_id": parent_id,
                "parent_text": "Quarterly revenue grew because the North region expanded its customer base.",
                "figure_ids": [figure_id],
                "table_ids": [table_id],
            },
            {
                "parent_id": unrelated_parent_id,
                "parent_text": "Facilities maintenance costs remained stable during the reporting period.",
                "figure_ids": [],
                "table_ids": [],
            },
        ],
        "figures": [
            {
                "figure_id": figure_id,
                "caption": "North region revenue growth increased quarter over quarter.",
                "bounding_boxes": [{"page": 1, "left": 10, "top": 20, "right": 100, "bottom": 120}],
            }
        ],
        "tables": [
            {
                "table_id": table_id,
                "markdown": "| Region | Revenue growth |\n| --- | --- |\n| North | 18 percent |",
                "heading": "Regional revenue growth",
                "caption": "Quarterly regional revenue growth",
                "context": "The North region delivered the strongest revenue growth.",
                "bounding_boxes": [{"page": 1, "left": 20, "top": 150, "right": 200, "bottom": 240}],
                "row_count": 2,
                "column_count": 2,
                "chunk_ids": [table_chunk_id],
            }
        ],
        "table_chunks": [
            {
                "table_chunk_id": table_chunk_id,
                "table_id": table_id,
                "row_start": 1,
                "row_end": 2,
                "text_with_context": (
                    "Heading: Regional revenue growth\n"
                    "Caption: Quarterly regional revenue growth\n"
                    "| Region | Revenue growth |\n| North | 18 percent |"
                ),
            }
        ],
        "children": [
            {
                "chunk_id": f"{parent_id}-child-001",
                "parent_id": parent_id,
                "text_with_context": (
                    "Document summary: Quarterly revenue growth report.\n"
                    "The North region expanded its customer base and delivered 18 percent revenue growth."
                ),
                "parent_text": "Quarterly revenue grew because the North region expanded its customer base.",
                "metadata": {"page_numbers": [1]},
            },
            {
                "chunk_id": f"{unrelated_parent_id}-child-001",
                "parent_id": unrelated_parent_id,
                "text_with_context": "Document summary: Quarterly report. Facilities maintenance costs stayed stable.",
                "parent_text": "Facilities maintenance costs remained stable during the reporting period.",
                "metadata": {"page_numbers": [2]},
            },
        ],
    }


def _assert_persisted_two_tier_records(document_id: str) -> None:
    """Assert the database holds the normalized document, parent, child, and assets."""
    with psycopg.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    (SELECT count(*) FROM parents WHERE doc_id = %s),
                    (SELECT count(*) FROM children WHERE doc_id = %s),
                    (SELECT count(*) FROM figures WHERE doc_id = %s),
                    (SELECT count(*) FROM tables WHERE doc_id = %s),
                    (SELECT count(*) FROM table_chunks WHERE doc_id = %s)
                """,
                (document_id, document_id, document_id, document_id, document_id),
            )
            assert cursor.fetchone() == (2, 2, 1, 1, 1)


def _delete_test_document(document_id: str) -> None:
    """Remove the unique integration-test document through its cascading root row."""
    with psycopg.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM documents WHERE id = %s", (document_id,))


def test_two_tier_retrieval_round_trip_uses_real_postgres_and_gemini() -> None:
    """Create normalized tiers, retrieve joined evidence, and clean up the test document."""
    document_id = f"e2e-two-tier-{uuid4().hex}"
    bundle = _bundle(document_id)

    logger.info("E2E retrieval step 1/5: initialize pgvector schema")
    initialize_schema()
    try:
        logger.info("E2E retrieval step 2/5: embed and ingest normalized bundle", extra={"document_id": document_id})
        assert ingest_bundle(bundle) == {
            "parents": 2,
            "figures": 1,
            "tables": 1,
            "table_chunks": 1,
            "children": 2,
        }

        logger.info("E2E retrieval step 3/5: verify normalized parent-child and asset rows")
        _assert_persisted_two_tier_records(document_id)

        logger.info("E2E retrieval step 4/5: run hybrid RRF search and relational join")
        response = hybrid_search_and_join("North regional revenue growth", top_k=1)

        logger.info("E2E retrieval step 5/5: verify grounded two-tier evidence")
        assert response["status"] == "grounded"
        evidence = response["evidence"]
        assert len(evidence) == 1
        result = evidence[0]
        assert result["document_id"] == document_id
        assert result["parent_id"] == bundle["parents"][0]["parent_id"]
        assert "North region" in result["parent_text"]
        assert result["figures"][0]["figure_id"] == bundle["figures"][0]["figure_id"]
        assert result["tables"][0]["table_id"] == bundle["tables"][0]["table_id"]
        assert result["matched_table_chunks"][0]["table_chunk_id"] == bundle["table_chunks"][0]["table_chunk_id"]
        assert "18 percent" in result["matched_table_chunks"][0]["text_with_context"]
        assert result["reranker_score"] >= 0.0
        logger.info("E2E retrieval complete", extra={"document_id": document_id, "parent_id": result["parent_id"]})
    finally:
        _delete_test_document(document_id)
        logger.info("E2E retrieval cleanup complete", extra={"document_id": document_id})
