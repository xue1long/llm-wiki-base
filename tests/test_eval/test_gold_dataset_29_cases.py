"""Tests for the 29-case gold dataset (C-3.2 / G8).

Each of the 4 dimension YAML files is loaded by `scripts.kc_eval` and must
contribute the expected case counts and coverage dimensions:

  * source_trust.yaml  — 5 cases  (SourceTrust.primary/official/expert/secondary/unknown)
  * evidence_span.yaml — 5 cases  (EvidenceType.direct_quote/structured_source/code/computed/inferred)
  * conflict.yaml      — 10 cases (Conflict.actual/conditional/temporal/perspective/unresolved/none × 2)
  * identity.yaml      — 9 cases  (Identity.merge/supersede/keep_separate × 3)

Total: 29 cases. The `test_total_case_count_is_29` test enforces the grand
total and is the single hard assertion — every other dimension test is
safe to skip when its YAML is missing.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path


def _kc_eval():
    """Import scripts.kc_eval via importlib (see test_gold_dataset_schema.py for rationale)."""
    for name in [n for n in sys.modules if n == "scripts" or n.startswith("scripts.")]:
        del sys.modules[name]
    return importlib.import_module("scripts.kc_eval")


def test_source_trust_yaml_has_5_cases():
    """source_trust.yaml 含 5 case 且全部 schema 完整"""
    evaluate_gold_dataset = _kc_eval().evaluate_gold_dataset
    path = Path("docs/evaluation/cases/source_trust.yaml")
    report = evaluate_gold_dataset(path)
    assert report["case_count"] == 5
    assert report["passed_count"] == 5
    assert all(r["passed"] for r in report["results"])


def test_evidence_span_yaml_has_5_cases():
    """evidence_span.yaml 含 5 case"""
    evaluate_gold_dataset = _kc_eval().evaluate_gold_dataset
    path = Path("docs/evaluation/cases/evidence_span.yaml")
    report = evaluate_gold_dataset(path)
    assert report["case_count"] == 5
    assert report["passed_count"] == 5
    assert all(r["passed"] for r in report["results"])


def test_conflict_yaml_has_10_cases_covering_6_types():
    """conflict.yaml 含 10 case 覆盖 6 类冲突（actual/conditional/temporal/perspective/unresolved/none 各 2）"""
    evaluate_gold_dataset = _kc_eval().evaluate_gold_dataset
    path = Path("docs/evaluation/cases/conflict.yaml")
    report = evaluate_gold_dataset(path)
    assert report["case_count"] == 10
    assert report["passed_count"] == 10

    # 验证 6 类全部覆盖：actual/conditional/temporal/perspective 各 2 例，unresolved/none 各 1 例
    coverage = report["coverage_matrix"]
    expected_counts = {
        "actual": 2,
        "conditional": 2,
        "temporal": 2,
        "perspective": 2,
        "unresolved": 1,
        "none": 1,
    }
    for conflict_type, expected_count in expected_counts.items():
        key = f"Conflict.{conflict_type}"
        assert key in coverage, f"缺少 {key} 维度覆盖"
        assert coverage[key] == expected_count, (
            f"{key} 覆盖 {coverage[key]} != {expected_count}"
        )


def test_identity_yaml_has_9_cases_covering_3_actions():
    """identity.yaml 含 9 case 覆盖 3 种 action（merge/supersede/keep_separate 各 3）"""
    evaluate_gold_dataset = _kc_eval().evaluate_gold_dataset
    path = Path("docs/evaluation/cases/identity.yaml")
    report = evaluate_gold_dataset(path)
    assert report["case_count"] == 9
    assert report["passed_count"] == 9

    # 验证 3 种 action 各覆盖 3 case
    coverage = report["coverage_matrix"]
    for action in ["merge", "supersede", "keep_separate"]:
        key = f"Identity.{action}"
        assert key in coverage, f"缺少 {key} 维度覆盖"
        assert coverage[key] == 3, f"{key} 覆盖 {coverage[key]} != 3"


def test_total_case_count_is_29():
    """4 个 YAML 总计 29 case — hard assertion, not skipped"""
    evaluate_gold_dataset = _kc_eval().evaluate_gold_dataset
    cases_dir = Path("docs/evaluation/cases")
    assert cases_dir.exists(), f"cases directory missing: {cases_dir}"

    total = 0
    breakdown: dict[str, int] = {}
    for yaml_file in sorted(cases_dir.glob("*.yaml")):
        if yaml_file.name.startswith("_"):
            continue  # skip _schema.yaml
        report = evaluate_gold_dataset(yaml_file)
        total += report["case_count"]
        breakdown[yaml_file.name] = report["case_count"]

    assert total == 29, f"实际 case 总数: {total} (breakdown: {breakdown})"
    # Sanity: 4 dimension files expected
    assert len(breakdown) == 4, f"期望 4 个 YAML,实际 {len(breakdown)}: {list(breakdown.keys())}"
