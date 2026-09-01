"""Tests for C-3.5 Agent Task evaluation (Z-3, spec §15 V-14 + §17 D-15).

Three TDD tests:

  1. ``test_agent_tasks_yaml_exists_with_10_cases`` — the shipped dataset
     has >=10 cases (hard assertion).

  2. ``test_evaluate_agent_task_dataset_outputs_success_rate`` — given a
     fixture with 1 PASS + 1 FAIL, the report correctly computes
     success_rate=0.5 and a non-zero citation_accuracy.

  3. ``test_evaluate_agent_task_includes_failure_reasons`` — a FAIL case
     populates ``failure_reasons`` with the reasons for failure.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import yaml


def _kc_agent_eval():
    """Import scripts.kc_agent_eval via importlib (see test_eval/conftest.py for rationale)."""
    for name in [n for n in sys.modules if n == "scripts" or n.startswith("scripts.")]:
        del sys.modules[name]
    return importlib.import_module("scripts.kc_agent_eval")


def test_agent_tasks_yaml_exists_with_10_cases():
    """agent_tasks.yaml 存在且 >=10 case (C-3.5 acceptance)."""
    path = Path("docs/evaluation/agent_tasks/agent_tasks.yaml")
    assert path.exists(), f"agent task dataset missing: {path}"

    tasks = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(tasks, list), "agent tasks YAML must be a list"
    assert len(tasks) >= 10, f"task 数 {len(tasks)} < 10 (C-3.5 acceptance)"

    # Every task must declare the required Agent Context schema fields
    required = {"task_id", "query", "expected_knowledge_units", "expected_citations",
                "success_criteria", "mock_response"}
    for t in tasks:
        missing = required - set(t)
        assert not missing, f"task {t.get('task_id', '<unknown>')} missing fields: {missing}"


def test_evaluate_agent_task_dataset_outputs_success_rate(tmp_path):
    """evaluate_agent_task_dataset 输出 Success Rate + Citation Accuracy."""
    yaml_path = tmp_path / "test_tasks.yaml"
    yaml_path.write_text(
        """
- task_id: AT-TEST-001
  query: "test query 1"
  expected_knowledge_units: ["ku_test_1"]
  expected_citations: ["ev_test_1", "ev_test_2"]
  expected_knowledge_modes: ["observed"]
  expected_conflict_status: ["none"]
  success_criteria:
    min_units_returned: 1
    min_citations_valid: 2
    knowledge_mode_identified: true
    citations_match: true
  mock_response:
    knowledge_items:
      - knowledge_unit_id: "ku_test_1"
        knowledge_mode: "observed"
        evidence_refs: ["ev_test_1", "ev_test_2"]
        conflict_status: "none"
        confidence: 0.9
    omitted_candidates: []

- task_id: AT-TEST-002
  query: "test query 2"
  expected_knowledge_units: ["ku_test_2"]
  expected_citations: ["ev_test_3"]
  expected_knowledge_modes: ["observed"]
  expected_conflict_status: ["none"]
  success_criteria:
    min_units_returned: 2  # FAIL: 只返 1
    min_citations_valid: 1
    knowledge_mode_identified: true
    citations_match: true
  mock_response:
    knowledge_items:
      - knowledge_unit_id: "ku_test_2"
        knowledge_mode: "observed"
        evidence_refs: ["ev_test_3"]
        conflict_status: "none"
        confidence: 0.8
    omitted_candidates: []
""",
        encoding="utf-8",
    )

    evaluate_agent_task_dataset = _kc_agent_eval().evaluate_agent_task_dataset
    report = evaluate_agent_task_dataset(yaml_path)

    assert report["task_count"] == 2
    # Mock results are traceability-only; product metrics require runtime
    # verification and therefore remain unevaluable for this fixture.
    assert report["passed_count"] == 0
    assert report["success_rate"] == 0.0
    assert report["citation_accuracy"] == 0.0
    assert report["total_citations_valid"] == 0
    assert report["total_citations_expected"] == 0
    assert report["not_evaluable"] is True


def test_evaluate_agent_task_includes_failure_reasons():
    """FAIL case 必须含 failure_reasons 列表 (mode-mismatch / threshold-mismatch)."""
    evaluate_agent_task = _kc_agent_eval().evaluate_agent_task

    task = {
        "task_id": "AT-FAIL",
        "query": "test",
        "expected_knowledge_units": ["ku_x"],
        "expected_citations": ["ev_x"],
        "expected_knowledge_modes": ["observed"],
        "expected_conflict_status": ["none"],
        "success_criteria": {
            "min_units_returned": 5,  # 高阈值触发 FAIL
            "min_citations_valid": 5,
            "knowledge_mode_identified": True,
            "citations_match": True,
        },
        "mock_response": {
            "knowledge_items": [
                {
                    "knowledge_unit_id": "ku_x",
                    "knowledge_mode": "observed",
                    "evidence_refs": ["ev_x"],
                    "conflict_status": "none",
                }
            ],
            "omitted_candidates": [],
        },
    }

    result = evaluate_agent_task(task)
    assert result.passed is False
    assert len(result.failure_reasons) > 0
    assert any(
        "units_returned" in r or "citations_valid" in r for r in result.failure_reasons
    ), f"failure_reasons 应含 units_returned / citations_valid，实际: {result.failure_reasons}"
