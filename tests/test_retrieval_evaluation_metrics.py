"""Unit coverage for retrieval benchmark metric calculations."""

import json
from pathlib import Path

import pytest

from retrieval.evaluate import _latency_summary, _load_cases, _metric_summary
from retrieval.pg_engine import _assess_confidence


def test_metric_summary_calculates_single_relevance_ranking_metrics() -> None:
    """Calculate recall, MRR, and nDCG for found and missed ground-truth results."""
    metrics = _metric_summary([1, 2, None], top_k=5)

    assert metrics["recall_at_1"] == 0.3333
    assert metrics["recall_at_k"] == 0.6667
    assert metrics["mrr"] == 0.5
    assert metrics["ndcg_at_k"] == 0.5436


def test_latency_summary_uses_nearest_rank_p95() -> None:
    """Report stable latency summaries for a small local benchmark sample."""
    assert _latency_summary([1.0, 2.0, 3.0, 4.0]) == {
        "mean_ms": 2.5,
        "p50_ms": 2.5,
        "p95_ms": 4.0,
    }


def test_confidence_declines_unsupported_vector_only_evidence() -> None:
    """Decline a loose semantic match when it has no lexical support or close vector distance."""
    confidence = _assess_confidence(
        [
            {
                "rrf_score": 0.01639,
                "vector_distance": 0.47136,
                "lexical_match": False,
                "rrf_score_margin": 0.000264,
            }
        ]
    )

    assert confidence["status"] == "not_found"
    assert any("Vector distance" in reason for reason in confidence["reasons"])


def test_confidence_accepts_loosened_vector_and_margin_thresholds() -> None:
    """Accept vector-only evidence inside the experimental relaxed thresholds."""
    confidence = _assess_confidence(
        [
            {
                "rrf_score": 0.012,
                "vector_distance": 0.46,
                "lexical_match": False,
                "rrf_score_margin": 0.0,
            }
        ]
    )

    assert confidence["status"] == "grounded"


def test_confidence_accepts_close_vector_only_evidence() -> None:
    """Retain legitimate semantic figure evidence even without a lexical hit."""
    confidence = _assess_confidence(
        [
            {
                "rrf_score": 0.01639,
                "vector_distance": 0.20960,
                "lexical_match": False,
                "rrf_score_margin": 0.000264,
            }
        ]
    )

    assert confidence["status"] == "grounded"


def test_figure_policy_rejects_missing_explicit_figure_number() -> None:
    """A nearby unrelated figure cannot satisfy an explicit figure-number request."""
    confidence = _assess_confidence(
        [
            {
                "rrf_score": 0.01639,
                "vector_distance": 0.2,
                "lexical_match": False,
                "rrf_score_margin": 0.000264,
                "figures": [{"caption": "Figure 29 governance structure"}],
                "child_text": "Figure 29",
                "parent_text": "Governance",
            }
        ],
        policy="figure",
        requested_figure=999,
    )

    assert confidence["status"] == "not_found"


def test_table_policy_accepts_structural_table_match_without_score_margin() -> None:
    """A strongly matched table row is not rejected because adjacent rows rank closely."""
    confidence = _assess_confidence(
        [
            {
                "rrf_score": 0.0161,
                "vector_distance": 0.35,
                "lexical_match": False,
                "rrf_score_margin": 0.0,
                "matched_table_chunks": [{"id": "table-row"}],
            }
        ],
        policy="table",
    )

    assert confidence["status"] == "grounded"


def test_load_cases_requires_the_configured_number_of_human_verified_rows(tmp_path: Path) -> None:
    """Prevent an annotation-ready set from being evaluated before human sign-off."""
    cases_path = tmp_path / "review.json"
    cases_path.write_text(
        json.dumps(
            {
                "require_human_verification": True,
                "minimum_human_verified_cases": 2,
                "cases": [
                    {"id": "one", "category": "text", "query": "Question one", "verification_status": "human_verified"},
                    {"id": "two", "category": "text", "query": "Question two", "verification_status": "pending_human_review"},
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="requires 2 human-verified cases"):
        _load_cases(cases_path)

    _, _, cases = _load_cases(cases_path, allow_unverified=True)
    assert len(cases) == 2
