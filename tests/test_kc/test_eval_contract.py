"""Tests for the ``not_applicable`` eval-dataset contract (Finding I-4).

Final whole-branch review Finding I-4: ``docs/evaluation/kc_mvp_cases.yaml``
had 10 negative-path cases (``task_result: failure`` with empty
``evidence_refs`` / ``expected_top_k``) carrying no ``not_applicable: true``
marker, so "no expectations" looked like a data gap. The fix:

* negative-path cases must explicitly declare ``not_applicable: true``;
* a ``not_applicable: true`` marker on a positive-path case is invalid
  (``not_applicable_misplaced``).

Enforcement in ``scripts/kc_eval.py::evaluate_gold_case`` is scoped to
Task-6 style cases that carry the evaluation-contract fields (``mode`` /
``runtime_verified``); legacy pre-Task-6 datasets predate the contract.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_EVAL_SCRIPT = _REPO / "scripts" / "kc_eval.py"


def _load_eval():
    """Load scripts/kc_eval.py by file path (sibling-project safe).

    A sibling project exposes its own ``scripts`` regular package via
    ``sys.path``; Python prefers that regular package over this repo's
    namespace-package ``scripts/`` regardless of order, so a plain
    ``import scripts.kc_eval`` would resolve to the sibling. Loading the
    file directly (as in tests/test_eval/test_gold_dataset_100_cases.py)
    bypasses the package machinery entirely.
    """
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


def _base_case(**overrides) -> dict:
    """Minimal Task-6 style gold case (full required schema + mode fields)."""
    case = {
        "case_id": "CT-001",
        "query": "test query",
        "source_type": "manual",
        "language": "en",
        "context": {"domain": "knowledge_management", "platform": "web"},
        "query_time": 1734567890000,
        "object_truth": {"type": "knowledge_unit", "id": "ku_test"},
        "identity_key": "id-v1:test",
        "resolution_action": "create",
        "integrity_status": "verified",
        "expected_top_k": [{"knowledge_unit_id": "ku_test", "score": 0.95}],
        "evidence_refs": ["ev_test"],
        "task_result": "success",
        "mode": "mock",
        "runtime_verified": False,
    }
    case.update(overrides)
    return case


def test_negative_path_case_without_not_applicable_is_invalid(eval_mod):
    """Negative-path case missing not_applicable → failed + invalid_fields."""
    case = _base_case(
        case_id="CT-NEG-MISSING",
        resolution_action="quarantine",
        integrity_status="quarantined",
        expected_top_k=[],
        evidence_refs=[],
        task_result="failure",
    )

    result = eval_mod.evaluate_gold_case(case)

    assert result["passed"] is False
    assert result["scores"]["invalid_fields"] == ["not_applicable"]


def test_negative_path_case_with_not_applicable_passes(eval_mod):
    """Negative-path case that declares not_applicable: true → valid."""
    case = _base_case(
        case_id="CT-NEG-OK",
        resolution_action="quarantine",
        integrity_status="quarantined",
        expected_top_k=[],
        evidence_refs=[],
        task_result="failure",
        not_applicable=True,
    )

    result = eval_mod.evaluate_gold_case(case)

    assert result["passed"] is True
    assert result["scores"]["invalid_fields"] == []
    assert result["scores"]["not_applicable"] is True


def test_positive_path_case_with_not_applicable_is_invalid(eval_mod):
    """not_applicable: true on a positive-path case is misplaced → invalid."""
    case = _base_case(
        case_id="CT-POS-MISPLACED",
        not_applicable=True,
    )

    result = eval_mod.evaluate_gold_case(case)

    assert result["passed"] is False
    assert result["scores"]["invalid_fields"] == ["not_applicable_misplaced"]


def test_positive_path_case_without_not_applicable_passes(eval_mod):
    """Positive-path case without the marker → valid (unchanged contract)."""
    case = _base_case(case_id="CT-POS-OK")

    result = eval_mod.evaluate_gold_case(case)

    assert result["passed"] is True
    assert result["scores"]["invalid_fields"] == []


def test_legacy_style_case_not_subject_to_contract(eval_mod):
    """Pre-Task-6 cases (no mode field) skip the not_applicable gate."""
    case = _base_case(
        case_id="CT-LEGACY",
        expected_top_k=[],
        evidence_refs=[],
        task_result="failure",
    )
    del case["mode"]
    del case["runtime_verified"]

    result = eval_mod.evaluate_gold_case(case)

    assert result["passed"] is True
    assert result["scores"]["invalid_fields"] == []


def test_mvp_dataset_declares_not_applicable_on_all_negative_cases(eval_mod):
    """The 30-case MVP dataset satisfies the contract end-to-end."""
    dataset_path = Path("docs/evaluation/kc_mvp_cases.yaml")
    assert dataset_path.exists(), f"Missing dataset: {dataset_path}"

    report = eval_mod.evaluate_gold_dataset(dataset_path)

    assert report["case_count"] == 30
    assert report["passed_count"] == 30

    # Every negative-path case must carry the marker (exactly the 10
    # quarantine/conflict/supersede outcomes).
    marked = 0
    import yaml

    for case in yaml.safe_load(dataset_path.read_text(encoding="utf-8")):
        if not case.get("expected_top_k") and not case.get("evidence_refs"):
            assert case.get("not_applicable") is True, case["case_id"]
            marked += 1
    assert marked == 10
