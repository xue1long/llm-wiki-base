from __future__ import annotations

from types import SimpleNamespace

from src.kc.integrity.closure import check_default_closure


def _assert_operation_report_shape(report: dict) -> None:
    assert report["passed"] in (True, False)
    assert isinstance(report["reason_codes"], tuple)
    assert all(isinstance(code, str) for code in report["reason_codes"])
    assert isinstance(report["operation_id"], str)


def test_closure_without_integrity_report_fails_closed() -> None:
    obj = SimpleNamespace(id="ko-1", status="verified", knowledge_mode="observed", claim_ids=[])

    report = check_default_closure(obj)

    assert report.passed is False
    assert report.hard_gates_passed is False
    failed = report.get_failed_conditions()
    assert "context_resolution_not_unresolved" in failed
    check = next(c for c in report.checks if c.condition_name == "context_resolution_not_unresolved")
    assert check.details == "missing_integrity_report"


def test_operation_report_contract_freezes_required_fields_only() -> None:
    success = {
        "passed": True,
        "reason_codes": (),
        "operation_id": "op-1",
    }
    conflict = {
        "passed": False,
        "reason_codes": ("version_conflict",),
        "operation_id": "op-1",
    }

    _assert_operation_report_shape(success)
    _assert_operation_report_shape(conflict)
    assert conflict["reason_codes"] == ("version_conflict",)
