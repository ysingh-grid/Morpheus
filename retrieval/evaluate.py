"""Benchmark the live two-stage retrieval engine against grounded query cases."""

from __future__ import annotations

import argparse
import json
import logging
import math
import time
from pathlib import Path
from statistics import mean, median
from typing import Any, NotRequired, TypedDict

from retrieval.pg_engine import (
    HYBRID_SEARCH_AND_JOIN_SQL,
    RRF_CANDIDATE_MULTIPLIER,
    RRF_K,
    _database_url,
    _assess_confidence,
    _embed,
    _flashrank_rerank,
    _psycopg,
    _vector_literal,
    hybrid_search_and_join,
)

logger = logging.getLogger(__name__)
DEFAULT_CASES_PATH = Path("retrieval/evaluation_cases_ifc_2024.json")
DEFAULT_REPORT_PATH = Path("dummy_data/ifc-annual-report-2024-financials.retrieval-evaluation.json")


class EvaluationCase(TypedDict):
    """One manually grounded retrieval question and its expected assets."""

    id: str
    category: str
    query: str
    expected_parent_id: NotRequired[str]
    expected_table_id: NotRequired[str]
    expected_figure_id: NotRequired[str]
    expected_status: NotRequired[str]


def _load_cases(cases_path: Path, allow_unverified: bool = False) -> tuple[str, int, list[EvaluationCase]]:
    """Load and validate a document-specific evaluation matrix."""
    payload = json.loads(cases_path.read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Evaluation cases must contain at least one case.")
    for case in cases:
        if not all(isinstance(case.get(key), str) for key in ("id", "category", "query")):
            raise ValueError("Every evaluation case requires string id, category, and query fields.")
    top_k = payload.get("top_k", 5)
    if not isinstance(top_k, int) or top_k < 1:
        raise ValueError("Evaluation top_k must be a positive integer.")
    if payload.get("require_human_verification") and not allow_unverified:
        verified_cases = [case for case in cases if case.get("verification_status") == "human_verified"]
        minimum_verified_cases = payload.get("minimum_human_verified_cases", len(cases))
        if len(verified_cases) < minimum_verified_cases:
            raise RuntimeError(
                f"Evaluation requires {minimum_verified_cases} human-verified cases; "
                f"only {len(verified_cases)} are verified."
            )
        cases = verified_cases
    return str(payload.get("name", cases_path.stem)), top_k, cases


def _run_rrf_stage(query: str, top_k: int) -> tuple[list[dict[str, Any]], float, float]:
    """Execute the SQL RRF stage and report embedding and SQL latency in milliseconds."""
    embedding_started = time.perf_counter()
    query_embedding = _embed([query])[0]
    embedding_ms = (time.perf_counter() - embedding_started) * 1_000
    candidate_limit = top_k * RRF_CANDIDATE_MULTIPLIER

    sql_started = time.perf_counter()
    psycopg = _psycopg()
    with psycopg.connect(_database_url()) as connection:
        with connection.cursor(row_factory=psycopg.rows.dict_row) as cursor:
            cursor.execute(
                HYBRID_SEARCH_AND_JOIN_SQL,
                (
                    _vector_literal(query_embedding),
                    query,
                    candidate_limit,
                    candidate_limit,
                    candidate_limit,
                    RRF_K,
                    candidate_limit,
                ),
            )
            records = list(cursor.fetchall())
    sql_ms = (time.perf_counter() - sql_started) * 1_000
    return records, embedding_ms, sql_ms


def _rank(records: list[dict[str, Any]], key: str, expected_id: str, top_k: int) -> int | None:
    """Return the one-based rank at which a parent or linked asset first appears."""
    for rank, record in enumerate(records[:top_k], start=1):
        if key == "parent_id" and record["parent_id"] == expected_id:
            return rank
        asset_group = "tables" if key == "table_id" else "figures"
        asset_id = "table_id" if key == "table_id" else "figure_id"
        if any(asset.get(asset_id) == expected_id for asset in record[asset_group]):
            return rank
    return None


def _metric_summary(ranks: list[int | None], top_k: int) -> dict[str, float]:
    """Calculate retrieval metrics for cases with a single known relevant result."""
    if not ranks:
        return {"recall_at_1": 0.0, "recall_at_k": 0.0, "mrr": 0.0, "ndcg_at_k": 0.0}
    recall_at_1 = sum(rank == 1 for rank in ranks) / len(ranks)
    recall_at_k = sum(rank is not None for rank in ranks) / len(ranks)
    mrr = sum(1 / rank for rank in ranks if rank is not None) / len(ranks)
    ndcg_at_k = sum(1 / math.log2(rank + 1) for rank in ranks if rank is not None) / len(ranks)
    return {
        "recall_at_1": round(recall_at_1, 4),
        "recall_at_k": round(recall_at_k, 4),
        "mrr": round(mrr, 4),
        "ndcg_at_k": round(ndcg_at_k, 4),
    }


def _latency_summary(samples: list[float]) -> dict[str, float]:
    """Summarize per-query latency samples in milliseconds."""
    if not samples:
        return {"mean_ms": 0.0, "p50_ms": 0.0, "p95_ms": 0.0}
    sorted_samples = sorted(samples)
    p95_index = math.ceil(0.95 * len(sorted_samples)) - 1
    return {
        "mean_ms": round(mean(samples), 2),
        "p50_ms": round(median(samples), 2),
        "p95_ms": round(sorted_samples[p95_index], 2),
    }


def _stage_result(records: list[dict[str, Any]], case: EvaluationCase, top_k: int) -> dict[str, Any]:
    """Record ranks and returned IDs for one retrieval stage."""
    result: dict[str, Any] = {
        "parent_ids": [record["parent_id"] for record in records[:top_k]],
        "table_ids": [[table["table_id"] for table in record["tables"]] for record in records[:top_k]],
        "figure_ids": [[figure["figure_id"] for figure in record["figures"]] for record in records[:top_k]],
    }
    if expected_parent_id := case.get("expected_parent_id"):
        result["parent_rank"] = _rank(records, "parent_id", expected_parent_id, top_k)
    if expected_table_id := case.get("expected_table_id"):
        result["table_rank"] = _rank(records, "table_id", expected_table_id, top_k)
    if expected_figure_id := case.get("expected_figure_id"):
        result["figure_rank"] = _rank(records, "figure_id", expected_figure_id, top_k)
    return result


def evaluate(
    cases_path: Path = DEFAULT_CASES_PATH,
    report_path: Path = DEFAULT_REPORT_PATH,
    allow_unverified: bool = False,
) -> dict[str, Any]:
    """Run all cases through RRF and FlashRank and write a JSON benchmark report."""
    benchmark_name, top_k, cases = _load_cases(cases_path, allow_unverified=allow_unverified)
    report_cases: list[dict[str, Any]] = []
    stage_one_parent_ranks: list[int | None] = []
    stage_two_parent_ranks: list[int | None] = []
    stage_one_table_ranks: list[int | None] = []
    stage_two_table_ranks: list[int | None] = []
    stage_one_figure_ranks: list[int | None] = []
    stage_two_figure_ranks: list[int | None] = []
    embedding_latencies: list[float] = []
    sql_latencies: list[float] = []
    rerank_latencies: list[float] = []
    total_latencies: list[float] = []
    confidence_decisions: list[bool] = []

    for case in cases:
        logger.info("Running retrieval evaluation case: %s (%s)", case["id"], case["category"])
        if case["category"] == "validation":
            try:
                hybrid_search_and_join(case["query"], top_k=top_k)
            except ValueError as error:
                report_cases.append({"id": case["id"], "status": "passed", "message": str(error)})
            else:
                report_cases.append({"id": case["id"], "status": "failed", "message": "blank query was accepted"})
            continue

        started = time.perf_counter()
        raw_records, embedding_ms, sql_ms = _run_rrf_stage(case["query"], top_k)
        confidence = _assess_confidence(raw_records)
        expected_status = case.get("expected_status")
        if expected_status in {"not_found", "clarification_needed"}:
            total_ms = (time.perf_counter() - started) * 1_000
            report_cases.append(
                {
                    "id": case["id"],
                    "category": case["category"],
                    "query": case["query"],
                    "expected_status": expected_status,
                    "confidence_decision": confidence,
                    "status_passed": confidence["status"] == expected_status,
                    "latency_ms": {
                        "embedding": round(embedding_ms, 2),
                        "sql": round(sql_ms, 2),
                        "rerank": 0.0,
                        "total": round(total_ms, 2),
                    },
                }
            )
            confidence_decisions.append(confidence["status"] == expected_status)
            embedding_latencies.append(embedding_ms)
            sql_latencies.append(sql_ms)
            rerank_latencies.append(0.0)
            total_latencies.append(total_ms)
            continue
        rerank_started = time.perf_counter()
        reranked_records = _flashrank_rerank(case["query"], raw_records, top_k)
        rerank_ms = (time.perf_counter() - rerank_started) * 1_000
        total_ms = (time.perf_counter() - started) * 1_000
        stage_one = _stage_result(raw_records, case, top_k)
        stage_two = _stage_result(reranked_records, case, top_k)
        report_case: dict[str, Any] = {
            "id": case["id"],
            "category": case["category"],
            "query": case["query"],
            "stage_one_rrf": stage_one,
            "stage_two_reranked": stage_two,
            "latency_ms": {
                "embedding": round(embedding_ms, 2),
                "sql": round(sql_ms, 2),
                "rerank": round(rerank_ms, 2),
                "total": round(total_ms, 2),
            },
            "confidence_decision": confidence,
        }
        if case["category"] == "unsupported":
            report_case["diagnostic"] = "unsupported query evaluated against the confidence threshold"
        else:
            if "parent_rank" in stage_one:
                stage_one_parent_ranks.append(stage_one["parent_rank"])
                stage_two_parent_ranks.append(stage_two["parent_rank"])
            if "table_rank" in stage_one:
                stage_one_table_ranks.append(stage_one["table_rank"])
                stage_two_table_ranks.append(stage_two["table_rank"])
            if "figure_rank" in stage_one:
                stage_one_figure_ranks.append(stage_one["figure_rank"])
                stage_two_figure_ranks.append(stage_two["figure_rank"])
        report_cases.append(report_case)
        embedding_latencies.append(embedding_ms)
        sql_latencies.append(sql_ms)
        rerank_latencies.append(rerank_ms)
        total_latencies.append(total_ms)

    report = {
        "benchmark": benchmark_name,
        "top_k": top_k,
        "human_verification_bypassed": allow_unverified,
        "quality_metrics": {
            "parent": {"stage_one_rrf": _metric_summary(stage_one_parent_ranks, top_k), "stage_two_reranked": _metric_summary(stage_two_parent_ranks, top_k)},
            "table": {"stage_one_rrf": _metric_summary(stage_one_table_ranks, top_k), "stage_two_reranked": _metric_summary(stage_two_table_ranks, top_k)},
            "figure": {"stage_one_rrf": _metric_summary(stage_one_figure_ranks, top_k), "stage_two_reranked": _metric_summary(stage_two_figure_ranks, top_k)},
            "confidence_decision_accuracy": (
                round(sum(confidence_decisions) / len(confidence_decisions), 4)
                if confidence_decisions
                else None
            ),
        },
        "latency_metrics_ms": {
            "embedding": _latency_summary(embedding_latencies),
            "sql_rrf_join": _latency_summary(sql_latencies),
            "flashrank": _latency_summary(rerank_latencies),
            "end_to_end": _latency_summary(total_latencies),
        },
        "cases": report_cases,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    logger.info("Retrieval evaluation complete", extra={"report_path": str(report_path), "case_count": len(cases)})
    return report


def main() -> None:
    """Run the live retrieval benchmark from the command line."""
    parser = argparse.ArgumentParser(description="Evaluate PostgreSQL RRF and FlashRank retrieval quality.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH, help="Ground-truth case matrix.")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH, help="JSON report destination.")
    parser.add_argument(
        "--allow-unverified",
        action="store_true",
        help="Run a pending-human-review matrix as an explicitly unverified smoke benchmark.",
    )
    arguments = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx2").setLevel(logging.WARNING)
    report = evaluate(arguments.cases, arguments.report, allow_unverified=arguments.allow_unverified)
    print(json.dumps(report["quality_metrics"], indent=2))
    print(json.dumps(report["latency_metrics_ms"], indent=2))


if __name__ == "__main__":
    main()
