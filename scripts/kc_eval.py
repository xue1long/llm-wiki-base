"""Knowledge Compiler gold-dataset evaluator (C-3 / G8, v2.2 optimization #7).

Two public entry points:

  * ``evaluate_gold_case(case)`` — schema-validate a single gold case dict
    and return a per-case score dict (case_id / passed / scores).
  * ``evaluate_gold_dataset(dataset_path)`` — load a YAML file of cases
    and return a coverage report (case_count / tag_breakdown /
    coverage_matrix / not_evaluable / per-case results).

The CLI front-end aggregates one or more datasets and writes the report
either to stdout (JSON) or to ``--output``.

This file lives next to ``kc_retrieval_eval.py`` which evaluates the
legacy 3-case hardcoded retrieval fixture in
``docs/evaluation/retrieval_cases.json``. The two scripts are independent:
the legacy script keeps evaluating retrieval-only hits, while this one
evaluates the multi-dimensional gold dataset introduced in C-3.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml


# Spec §15 — every gold case MUST declare these fields.
REQUIRED_FIELDS: list[str] = [
    "case_id",
    "query",
    "source_type",
    "language",
    "context",
    "query_time",
    "object_truth",
    "identity_key",
    "resolution_action",
    "integrity_status",
    "expected_top_k",
    "evidence_refs",
    "task_result",
]


def evaluate_gold_case(case: dict[str, Any]) -> dict[str, Any]:
    """Schema-validate one gold case and return a score dict.

    Returned shape::

        {
            "case_id": <str>,
            "passed": <bool>,
            "scores": {
                "schema_completeness": <float 0..1>,
                "missing_fields": [..],
                "tag": <str>,
                "confidence": <str>,
            },
        }
    """
    case_id = case.get("case_id", "<missing>")

    missing = [field for field in REQUIRED_FIELDS if field not in case]
    completeness = (len(REQUIRED_FIELDS) - len(missing)) / len(REQUIRED_FIELDS)
    passed = len(missing) == 0

    return {
        "case_id": case_id,
        "passed": passed,
        "scores": {
            "schema_completeness": completeness,
            "missing_fields": missing,
            "tag": case.get("tag", "full"),
            "confidence": case.get("confidence", "high"),
        },
    }


def evaluate_gold_dataset(dataset_path: Path) -> dict[str, Any]:
    """Load a YAML dataset and produce a coverage report.

    Returned shape::

        {
            "dataset_path": <str>,
            "case_count": <int>,
            "passed_count": <int>,
            "tag_breakdown": {tag: count, ..},
            "coverage_matrix": {dimension: count, ..},
            "not_evaluable": <bool>,        # v2.2 optimization #7
            "results": [<evaluate_gold_case output>, ..],
        }
    """
    cases = yaml.safe_load(dataset_path.read_text(encoding="utf-8")) or []

    results = [evaluate_gold_case(case) for case in cases]

    tag_breakdown: dict[str, int] = {}
    coverage_matrix: dict[str, int] = {}
    for case, result in zip(cases, results):
        tag = result["scores"]["tag"]
        tag_breakdown[tag] = tag_breakdown.get(tag, 0) + 1

        dimension = case.get("coverage_dimension", "unknown")
        coverage_matrix[dimension] = coverage_matrix.get(dimension, 0) + 1

    passed_count = sum(1 for r in results if r["passed"])

    return {
        "dataset_path": str(dataset_path),
        "case_count": len(cases),
        "passed_count": passed_count,
        "tag_breakdown": tag_breakdown,
        "coverage_matrix": coverage_matrix,
        "not_evaluable": passed_count == 0,
        "results": results,
    }


def _aggregate_dataset_reports(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Combine per-dataset reports into a single aggregated report."""
    aggregated: dict[str, Any] = {
        "datasets": [],
        "total_case_count": 0,
        "total_passed_count": 0,
        "tag_breakdown": {},
        "coverage_matrix": {},
    }
    for report in reports:
        aggregated["datasets"].append(
            {
                "path": report["dataset_path"],
                "case_count": report["case_count"],
                "passed_count": report["passed_count"],
                "tag_breakdown": report["tag_breakdown"],
                "coverage_matrix": report["coverage_matrix"],
                "not_evaluable": report["not_evaluable"],
            }
        )
        aggregated["total_case_count"] += report["case_count"]
        aggregated["total_passed_count"] += report["passed_count"]
        for tag, count in report["tag_breakdown"].items():
            aggregated["tag_breakdown"][tag] = (
                aggregated["tag_breakdown"].get(tag, 0) + count
            )
        for dim, count in report["coverage_matrix"].items():
            aggregated["coverage_matrix"][dim] = (
                aggregated["coverage_matrix"].get(dim, 0) + count
            )
    return aggregated


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate gold datasets for the Knowledge Compiler pipeline."
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        action="append",
        help="YAML file(s) to evaluate. Can be specified multiple times.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write aggregated report to this JSON file (default: stdout).",
    )
    args = parser.parse_args()

    dataset_paths: list[Path] = list(args.dataset) if args.dataset else []
    if not dataset_paths:
        cases_dir = Path("docs/evaluation/cases")
        if cases_dir.exists():
            dataset_paths = [
                p
                for p in sorted(cases_dir.glob("*.yaml"))
                if not p.name.startswith("_")
            ]

    if not dataset_paths:
        print(
            "No dataset found. Pass --dataset PATH or create "
            "docs/evaluation/cases/*.yaml."
        )
        return

    reports = [evaluate_gold_dataset(path) for path in dataset_paths]
    aggregated = _aggregate_dataset_reports(reports)

    output_text = json.dumps(aggregated, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(output_text, encoding="utf-8")
        print(f"Wrote report to {args.output}")
    else:
        print(output_text)


if __name__ == "__main__":
    main()