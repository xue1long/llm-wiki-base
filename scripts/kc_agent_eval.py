"""Agent Task evaluation script (C-3.5 / Z-3, spec §15 V-14 + §17 D-15).

Evaluates a YAML dataset of agent tasks against their ``mock_response``
fixtures (Mode A: dry-run). Each case declares an expected retrieval /
citation / mode / conflict outcome; the evaluator returns a per-task
result plus an aggregate Success Rate and Citation Accuracy.

Returned aggregate shape::

    {
        "dataset_path": <str>,
        "task_count": <int>,
        "passed_count": <int>,
        "success_rate": <float>,
        "citation_accuracy": <float>,
        "total_citations_valid": <int>,
        "total_citations_expected": <int>,
        "results": [<per-task dict>, ...],
    }

Thresholds (spec §17 D-15):
    - Agent Task Success Rate >= 0.85
    - Citation Accuracy >= 0.95

Real agent runtime integration is a follow-up Z-3 task; this script
focuses on the dry-run evaluation pipeline.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class AgentTaskResult:
    task_id: str
    passed: bool
    units_returned: int
    units_expected: int
    citations_valid: int
    citations_expected: int
    knowledge_mode_identified: bool
    conflict_status_matched: bool
    omitted_reasons: list[str] = field(default_factory=list)
    failure_reasons: list[str] = field(default_factory=list)
    # Task 6 (plan 2026-08-29-...): ``mode`` records the evaluation mode
    # (``"mock"`` when judged by dry-run fixtures, ``"runtime"`` when the
    # real agent was executed). ``runtime_verified`` mirrors whether a
    # real provider was available at evaluation time. Aggregate reports
    # (see ``evaluate_agent_task_dataset``) separate mock results from
    # the product pass rate — only ``runtime_verified=True`` tasks count
    # toward ``success_rate``.
    mode: str = "mock"
    runtime_verified: bool = False


def evaluate_agent_task(task: dict[str, Any]) -> AgentTaskResult:
    """Evaluate one agent task against its mock_response.

    Mode A: dry-run with mock_response (not real agent runtime call).
    Real agent runtime integration is Z-3 follow-up task.

    Task 6 (plan 2026-08-29-...): every task carries an explicit
    ``mode`` (``mock`` | ``runtime``) and ``runtime_verified`` flag.
    When ``runtime_verified`` is False the task is recorded for
    traceability but excluded from the product-level ``success_rate``
    in the aggregate report.
    """
    task_id = task["task_id"]
    criteria = task["success_criteria"]
    mock = task.get("mock_response", {})
    items = mock.get("knowledge_items", [])
    omitted = mock.get("omitted_candidates", [])
    mode = str(task.get("mode", "mock"))
    runtime_verified = bool(task.get("runtime_verified", False))

    failure_reasons: list[str] = []

    # 1. units_returned count
    units_returned = len(items)
    if units_returned < criteria["min_units_returned"]:
        failure_reasons.append(
            f"units_returned {units_returned} < min_required {criteria['min_units_returned']}"
        )

    # 2. units_expected 匹配（subset check: every expected must be in actual）
    expected_ku_ids = set(task.get("expected_knowledge_units", []))
    actual_ku_ids = {item["knowledge_unit_id"] for item in items}
    if expected_ku_ids:
        units_match = expected_ku_ids.issubset(actual_ku_ids)
        if not units_match:
            missing = expected_ku_ids - actual_ku_ids
            failure_reasons.append(f"missing expected KU: {sorted(missing)}")

    # 3. citations_valid: how many expected citations appear in actual evidence_refs
    actual_citations: set[str] = set()
    for item in items:
        actual_citations.update(item.get("evidence_refs", []))
    expected_citations = set(task.get("expected_citations", []))
    citations_valid = len(actual_citations & expected_citations)
    if citations_valid < criteria["min_citations_valid"]:
        failure_reasons.append(
            f"citations_valid {citations_valid} < min_required {criteria['min_citations_valid']}"
        )

    # 4. knowledge_mode_identified: every returned item carries knowledge_mode
    knowledge_mode_identified = all("knowledge_mode" in item for item in items)
    if criteria.get("knowledge_mode_identified") and not knowledge_mode_identified:
        failure_reasons.append("missing knowledge_mode field in some items")

    # 5. conflict_status 匹配: every expected conflict_status must be present
    expected_conflicts = set(task.get("expected_conflict_status", []))
    actual_conflicts = {
        item.get("conflict_status") for item in items if "conflict_status" in item
    }
    if expected_conflicts:
        conflict_status_matched = expected_conflicts.issubset(actual_conflicts)
        if not conflict_status_matched:
            failure_reasons.append(
                f"conflict_status mismatch: expected {sorted(expected_conflicts)}, got {sorted(actual_conflicts)}"
            )
    else:
        conflict_status_matched = True

    # 6. omitted_candidates: 仅记录，不参与 PASS 判定（Integrity Gate 行为已由 #2/#3 体现）
    omitted_reasons = [o.get("reason", "") for o in omitted]

    passed = len(failure_reasons) == 0

    return AgentTaskResult(
        task_id=task_id,
        passed=passed,
        units_returned=units_returned,
        units_expected=len(expected_ku_ids),
        citations_valid=citations_valid,
        citations_expected=len(expected_citations),
        knowledge_mode_identified=knowledge_mode_identified,
        conflict_status_matched=conflict_status_matched,
        omitted_reasons=omitted_reasons,
        failure_reasons=failure_reasons,
        mode=mode,
        runtime_verified=runtime_verified,
    )


def evaluate_agent_task_dataset(dataset_path: Path) -> dict[str, Any]:
    """Evaluate all agent tasks in YAML file. Returns success rate + citation accuracy.

    Task 6 (plan 2026-08-29-...): mock results are recorded for
    traceability but excluded from ``success_rate`` (the product
    pass rate). The aggregate splits results into ``runtime_results``
    and ``mock_results``; downstream consumers can verify that
    ``runtime_count == 0`` → ``not_evaluable`` flag is True.
    """
    tasks = yaml.safe_load(dataset_path.read_text(encoding="utf-8")) or []

    results = [evaluate_agent_task(t) for t in tasks]
    runtime_results = [r for r in results if r.runtime_verified]
    mock_results = [r for r in results if not r.runtime_verified]
    passed = sum(1 for r in runtime_results if r.passed)
    total = len(results)
    runtime_total = len(runtime_results)

    # Citation Accuracy — over RUNTIME results only (mock not eligible)
    total_citations_valid = sum(r.citations_valid for r in runtime_results)
    total_citations_expected = sum(r.citations_expected for r in runtime_results)
    citation_accuracy = (
        total_citations_valid / total_citations_expected
        if total_citations_expected > 0
        else 0.0
    )

    # Success rate — over runtime results only (mock excluded).
    success_rate = passed / runtime_total if runtime_total > 0 else 0.0

    return {
        "dataset_path": str(dataset_path),
        "task_count": total,
        "runtime_count": runtime_total,
        "mock_count": len(mock_results),
        "passed_count": passed,
        "success_rate": success_rate,
        "citation_accuracy": citation_accuracy,
        "total_citations_valid": total_citations_valid,
        "total_citations_expected": total_citations_expected,
        "not_evaluable": runtime_total == 0,
        "results": [
            {
                "task_id": r.task_id,
                "passed": r.passed,
                "mode": r.mode,
                "runtime_verified": r.runtime_verified,
                "units_returned": r.units_returned,
                "units_expected": r.units_expected,
                "citations_valid": r.citations_valid,
                "citations_expected": r.citations_expected,
                "omitted_reasons": r.omitted_reasons,
                "failure_reasons": r.failure_reasons,
            }
            for r in results
        ],
        "runtime_results": [
            {"task_id": r.task_id, "passed": r.passed, "mode": r.mode}
            for r in runtime_results
        ],
        "mock_results": [
            {"task_id": r.task_id, "passed": r.passed, "mode": r.mode}
            for r in mock_results
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Agent Task dataset")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("docs/evaluation/agent_tasks/agent_tasks.yaml"),
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    if not args.dataset.exists():
        print(f"Dataset not found: {args.dataset}")
        return

    report = evaluate_agent_task_dataset(args.dataset)
    output = json.dumps(report, indent=2, ensure_ascii=False)

    if args.output:
        args.output.write_text(output, encoding="utf-8")
        print(f"Wrote report to {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
