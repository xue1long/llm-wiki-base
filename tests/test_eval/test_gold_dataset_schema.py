"""Tests for the gold dataset schema (spec §15) and the kc_eval evaluator.

Covers C-3 / G8 deliverable: schema documentation + 11 required fields,
plus the two public evaluator entry points (per-case + per-dataset).
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import yaml


def _kc_eval():
    """Import scripts.kc_eval via importlib so the namespace package wins.

    A sibling project (``D:\\5-Project\\2026814\\llm-wiki-base\\src\\``)
    exposes its own ``scripts`` regular package via ``sys.path``; Python's
    FileFinder prefers the regular package over a namespace-package
    directory of the same name, so a plain ``from scripts.kc_eval import
    ...`` resolves to the sibling and crashes. Clearing any cached
    ``scripts.*`` entries from ``sys.modules`` and importing via
    ``importlib`` defeats that resolution rule.
    """
    for name in [n for n in sys.modules if n == "scripts" or n.startswith("scripts.")]:
        del sys.modules[name]
    return importlib.import_module("scripts.kc_eval")


# Spec §15 — required fields for every gold case.
REQUIRED_FIELDS = [
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


def test_gold_case_schema_doc_has_required_fields():
    """_schema.yaml must document all required fields (spec §15)."""
    schema_path = Path("docs/evaluation/cases/_schema.yaml")
    assert schema_path.exists(), f"Schema doc not found: {schema_path}"

    content = schema_path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(content)

    # Schema must declare required_fields as a mapping.
    assert isinstance(parsed, dict), "Schema root must be a mapping"
    assert "required_fields" in parsed, "Schema must define required_fields"
    assert isinstance(parsed["required_fields"], dict), "required_fields must be a mapping"

    declared = set(parsed["required_fields"].keys())
    for field in REQUIRED_FIELDS:
        assert field in declared, f"Missing required field declaration: {field}"

    # Each required field must declare at minimum type + description.
    for field, spec in parsed["required_fields"].items():
        assert "type" in spec, f"{field} missing 'type'"
        assert "description" in spec, f"{field} missing 'description'"


def test_evaluate_gold_case_returns_score_dict():
    """evaluate_gold_case(case) returns score dict with case_id, passed, scores."""
    evaluate_gold_case = _kc_eval().evaluate_gold_case

    case = {
        "case_id": "TC-001",
        "query": "如何写爽点",
        "source_type": "url",
        "language": "zh",
        "context": {"domain": "novel_writing", "platform": "web"},
        "query_time": 1734567890000,
        "object_truth": {"type": "knowledge_unit", "id": "ku_xyz"},
        "identity_key": "id-v1:abc...",
        "resolution_action": "create",
        "integrity_status": "verified",
        "expected_top_k": [{"knowledge_unit_id": "ku_xyz", "score": 0.95}],
        "evidence_refs": ["ev_001", "ev_002"],
        "task_result": "success",
        "tag": "full",
    }

    result = evaluate_gold_case(case)

    assert result["case_id"] == "TC-001"
    assert result["passed"] is True, "Complete case should pass schema validation"
    assert "scores" in result
    scores = result["scores"]
    assert "schema_completeness" in scores
    assert scores["schema_completeness"] == 1.0, "All fields present → completeness 1.0"
    assert scores["missing_fields"] == []
    assert scores["tag"] == "full"


def test_evaluate_gold_case_flags_missing_fields():
    """evaluate_gold_case must report missing required fields."""
    evaluate_gold_case = _kc_eval().evaluate_gold_case

    case = {
        "case_id": "TC-INCOMPLETE",
        "query": "incomplete case",
        # All other required fields missing on purpose
    }

    result = evaluate_gold_case(case)

    assert result["passed"] is False
    missing = result["scores"]["missing_fields"]
    # All REQUIRED_FIELDS minus those present must appear in missing.
    expected_missing = sorted(set(REQUIRED_FIELDS) - {"case_id", "query"})
    assert sorted(missing) == expected_missing
    assert result["scores"]["schema_completeness"] < 1.0


def test_evaluate_gold_dataset_outputs_coverage_report(tmp_path):
    """evaluate_gold_dataset traverses YAML and outputs a coverage report."""
    yaml_path = tmp_path / "test_cases.yaml"
    yaml_path.write_text(
        """
- case_id: TC-001
  query: q1
  source_type: url
  language: zh
  context: {domain: test}
  query_time: 1734567890000
  object_truth: {type: knowledge_unit, id: ku_1}
  identity_key: id-v1:abc
  resolution_action: create
  integrity_status: verified
  expected_top_k: [{knowledge_unit_id: ku_1, score: 0.95}]
  evidence_refs: []
  task_result: success
  tag: full
  coverage_dimension: source_trust
- case_id: TC-002
  query: q2
  source_type: file
  language: zh
  context: {domain: test}
  query_time: 1734567890000
  object_truth: {type: knowledge_unit, id: ku_2}
  identity_key: id-v1:def
  resolution_action: merge
  integrity_status: candidate
  expected_top_k: [{knowledge_unit_id: ku_2, score: 0.8}]
  evidence_refs: []
  task_result: success
  tag: partial
  coverage_dimension: identity
- case_id: TC-003
  query: q3
  source_type: url
  language: en
  context: {domain: test}
  query_time: 1734567890000
  object_truth: {type: claim, id: cl_3}
  identity_key: id-v1:ghi
  resolution_action: conflict
  integrity_status: disputed
  expected_top_k: []
  evidence_refs: []
  task_result: failure
  tag: synthetic
  coverage_dimension: conflict
""",
        encoding="utf-8",
    )

    evaluate_gold_dataset = _kc_eval().evaluate_gold_dataset
    report = evaluate_gold_dataset(yaml_path)

    assert report["case_count"] == 3
    assert report["passed_count"] == 3
    assert report["tag_breakdown"] == {"full": 1, "partial": 1, "synthetic": 1}
    assert report["coverage_matrix"] == {
        "source_trust": 1,
        "identity": 1,
        "conflict": 1,
    }
    assert report["not_evaluable"] is False


def test_evaluate_gold_dataset_marks_not_evaluable_when_empty(tmp_path):
    """v2.2 optimization #7: not_evaluable flag when no case passes."""
    yaml_path = tmp_path / "empty_cases.yaml"
    yaml_path.write_text("[]", encoding="utf-8")

    evaluate_gold_dataset = _kc_eval().evaluate_gold_dataset
    report = evaluate_gold_dataset(yaml_path)

    assert report["case_count"] == 0
    assert report["passed_count"] == 0
    assert report["not_evaluable"] is True
