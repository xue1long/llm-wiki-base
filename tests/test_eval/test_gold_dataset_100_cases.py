"""Tests for expanded gold dataset (B-5 / F-2): 100 cases covering 4 dimensions."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_EVAL_SCRIPT = _REPO / "scripts" / "kc_eval.py"


def _load_eval():
    mod_name = "kc_eval"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, _EVAL_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def eval_mod():
    return _load_eval()


def test_source_trust_yaml_has_20_cases(eval_mod):
    path = Path("docs/evaluation/cases/source_trust.yaml")
    report = eval_mod.evaluate_gold_dataset(path)
    assert report["case_count"] == 20
    assert report["passed_count"] == 20
    # 5 authority_level × 4
    assert report["coverage_matrix"].get("SourceTrust.primary") == 4
    assert report["coverage_matrix"].get("SourceTrust.unknown") == 4


def test_evidence_span_yaml_has_20_cases(eval_mod):
    path = Path("docs/evaluation/cases/evidence_span.yaml")
    report = eval_mod.evaluate_gold_dataset(path)
    assert report["case_count"] == 20
    assert report["passed_count"] == 20
    assert report["coverage_matrix"].get("EvidenceType.direct_quote") == 4
    assert report["coverage_matrix"].get("EvidenceType.inferred") == 4


def test_conflict_yaml_has_30_cases(eval_mod):
    path = Path("docs/evaluation/cases/conflict.yaml")
    report = eval_mod.evaluate_gold_dataset(path)
    assert report["case_count"] == 30
    assert report["passed_count"] == 30
    # 6 conflict_type × 5 (覆盖矩阵无缺口)
    for ctype in ("actual", "conditional", "temporal", "perspective", "unresolved", "none"):
        assert report["coverage_matrix"].get(f"Conflict.{ctype}") == 5, f"缺口: {ctype}"


def test_identity_yaml_has_30_cases(eval_mod):
    path = Path("docs/evaluation/cases/identity.yaml")
    report = eval_mod.evaluate_gold_dataset(path)
    assert report["case_count"] == 30
    assert report["passed_count"] == 30
    for action in ("merge", "supersede", "keep_separate"):
        assert report["coverage_matrix"].get(f"Identity.{action}") == 10, f"缺口: {action}"


def test_total_case_count_is_100(eval_mod):
    """4 个 YAML 总计 100 case (spec §14 A0 Gate)."""
    cases_dir = Path("docs/evaluation/cases")
    total = 0
    passed = 0
    tag_breakdown = {}
    for yaml_file in sorted(cases_dir.glob("*.yaml")):
        if yaml_file.name.startswith("_"):
            continue
        report = eval_mod.evaluate_gold_dataset(yaml_file)
        total += report["case_count"]
        passed += report["passed_count"]
        for tag, count in report["tag_breakdown"].items():
            tag_breakdown[tag] = tag_breakdown.get(tag, 0) + count
    assert total == 100, f"实际 case 总数: {total}"
    assert passed == 100
    # tag 分布: full ≥ 60, partial ≤ 35, synthetic ≤ 10
    assert tag_breakdown.get("full", 0) >= 60, f"full 不足: {tag_breakdown.get('full', 0)}"
    assert tag_breakdown.get("partial", 0) <= 35, f"partial 过多: {tag_breakdown.get('partial', 0)}"
    assert tag_breakdown.get("synthetic", 0) <= 10, f"synthetic 过多: {tag_breakdown.get('synthetic', 0)}"
