"""Tests for kc_agent_eval mode/runtime_verified separation (Finding I-4).

Task 6 added explicit ``mode`` (``mock`` | ``runtime``) and
``runtime_verified`` fields to agent-task cases. The aggregate report
must keep the two populations separate: mock results are recorded for
traceability but EXCLUDED from ``success_rate`` (the product pass rate)
and from citation accuracy — only ``runtime_verified=True`` tasks count.

This file freezes that contract with one passing mock case and one
failing runtime case: if mock results leaked into the product rate the
``success_rate`` would be 0.5 instead of 0.0.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_AGENT_EVAL_SCRIPT = _REPO / "scripts" / "kc_agent_eval.py"


def _load_agent_eval():
    """Load scripts/kc_agent_eval.py by file path (sibling-project safe).

    See tests/test_kc/test_eval_contract.py for the rationale: a sibling
    project's ``scripts`` regular package shadows this repo's namespace
    package on ``sys.path``, so we bypass package import entirely.
    """
    mod_name = "kc_agent_eval"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, _AGENT_EVAL_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def agent_eval_mod():
    return _load_agent_eval()


def _passing_mock_task() -> dict:
    """A fully passing MOCK task — must never count toward success_rate."""
    return {
        "task_id": "mock-pass",
        "success_criteria": {"min_units_returned": 1, "min_citations_valid": 1},
        "expected_knowledge_units": ["ku_mock"],
        "expected_citations": ["ev_mock"],
        "expected_conflict_status": [],
        "mock_response": {
            "knowledge_items": [
                {
                    "knowledge_unit_id": "ku_mock",
                    "evidence_refs": ["ev_mock"],
                    "knowledge_mode": "observed",
                    "conflict_status": "none",
                }
            ],
            "omitted_candidates": [],
        },
        "mode": "mock",
        "runtime_verified": False,
    }


def _failing_runtime_task() -> dict:
    """A failing RUNTIME task — the only task eligible for success_rate."""
    return {
        "task_id": "runtime-fail",
        "success_criteria": {"min_units_returned": 1, "min_citations_valid": 1},
        "expected_knowledge_units": ["ku_runtime"],
        "expected_citations": ["ev_runtime"],
        "expected_conflict_status": [],
        "mock_response": {
            "knowledge_items": [],
            "omitted_candidates": [{"reason": "not retrieved"}],
        },
        "mode": "runtime",
        "runtime_verified": True,
    }


def _write_dataset(tmp_path: Path, tasks: list[dict]) -> Path:
    import yaml

    path = tmp_path / "agent_tasks.yaml"
    path.write_text(yaml.safe_dump(tasks, allow_unicode=True), encoding="utf-8")
    return path


def test_mock_results_excluded_from_success_rate(tmp_path, agent_eval_mod):
    """One passing mock + one failing runtime → success_rate reflects runtime only."""
    dataset = _write_dataset(
        tmp_path,
        [_passing_mock_task(), _failing_runtime_task()],
    )

    report = agent_eval_mod.evaluate_agent_task_dataset(dataset)

    assert report["task_count"] == 2
    assert report["runtime_count"] == 1
    assert report["mock_count"] == 1
    assert report["not_evaluable"] is False

    # The mock task passed but is excluded; the runtime task failed.
    assert report["passed_count"] == 0
    assert report["success_rate"] == 0.0
    # If the mock had leaked into the denominator: 0.5.


def test_mock_results_excluded_from_citation_accuracy(tmp_path, agent_eval_mod):
    """Citation accuracy is computed over runtime results only."""
    dataset = _write_dataset(
        tmp_path,
        [_passing_mock_task(), _failing_runtime_task()],
    )

    report = agent_eval_mod.evaluate_agent_task_dataset(dataset)

    # Runtime task expected 1 citation and produced none.
    assert report["total_citations_expected"] == 1
    assert report["total_citations_valid"] == 0
    assert report["citation_accuracy"] == 0.0


def test_runtime_results_and_mock_results_are_separated(tmp_path, agent_eval_mod):
    """Aggregate splits results into runtime_results vs mock_results."""
    dataset = _write_dataset(
        tmp_path,
        [_passing_mock_task(), _failing_runtime_task()],
    )

    report = agent_eval_mod.evaluate_agent_task_dataset(dataset)

    assert report["runtime_results"] == [
        {"task_id": "runtime-fail", "passed": False, "mode": "runtime"}
    ]
    assert report["mock_results"] == [
        {"task_id": "mock-pass", "passed": True, "mode": "mock"}
    ]


def test_runtime_passing_task_counts_toward_success_rate(tmp_path, agent_eval_mod):
    """A passing runtime task is the only way to raise the product rate."""
    runtime_pass = _failing_runtime_task()
    runtime_pass["task_id"] = "runtime-pass"
    runtime_pass["mock_response"]["knowledge_items"] = [
        {
            "knowledge_unit_id": "ku_runtime",
            "evidence_refs": ["ev_runtime"],
            "knowledge_mode": "observed",
            "conflict_status": "none",
        }
    ]
    dataset = _write_dataset(
        tmp_path,
        [_passing_mock_task(), runtime_pass],
    )

    report = agent_eval_mod.evaluate_agent_task_dataset(dataset)

    assert report["runtime_count"] == 1
    assert report["mock_count"] == 1
    assert report["passed_count"] == 1
    assert report["success_rate"] == 1.0
