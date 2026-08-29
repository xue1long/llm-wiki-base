from __future__ import annotations

from types import SimpleNamespace

from src.kc.integrity.closure import check_default_closure
from src.kc.integrity.gates import GateVerdict
from src.kc.integrity.orchestrator import GateResult, IntegrityReport


def _passing_integrity_report(object_id: str = "ko-pass") -> IntegrityReport:
    gate_results = (
        GateResult(
            gate_name="schema",
            order=1,
            verdict=GateVerdict.pass_(),
            skipped=False,
        ),
    )
    return IntegrityReport(
        object_id=object_id,
        gate_results=gate_results,
        passed=True,
        blocked=False,
        warnings=(),
    )


def _check(report, condition_name: str):
    return next(c for c in report.checks if c.condition_name == condition_name)


def _assert_no_assumed_details(report) -> None:
    for check in report.checks:
        assert "assumed" not in check.details
        assert "simplified" not in check.details


def test_missing_integrity_report_fails_closed() -> None:
    obj = SimpleNamespace(
        id="ko-missing-integrity",
        status="verified",
        knowledge_mode="observed",
        claim_ids=[],
        concept_status="verified",
        evidence_refs=["ev_001"],
        evidence_statuses=["active"],
        source_trust_statuses=["accepted"],
    )

    report = check_default_closure(obj)

    assert report.passed is False
    assert report.hard_gates_passed is False
    assert "context_resolution_not_unresolved" in report.get_failed_conditions()
    assert _check(report, "context_resolution_not_unresolved").details == "missing_integrity_report"
    _assert_no_assumed_details(report)


def test_missing_evidence_fails_closed() -> None:
    obj = SimpleNamespace(
        id="ko-missing-evidence",
        status="verified",
        knowledge_mode="observed",
        claim_ids=[],
        concept_status="verified",
        evidence_refs=[],
        evidence_statuses=[],
        source_trust_statuses=["accepted"],
    )

    report = check_default_closure(obj, _passing_integrity_report(obj.id))

    assert report.passed is False
    assert _check(report, "all_evidence_status_active").details == "missing_evidence"
    _assert_no_assumed_details(report)


def test_synthesized_missing_provenance_fails_closed() -> None:
    obj = SimpleNamespace(
        id="ko-missing-provenance",
        status="verified",
        knowledge_mode="synthesized",
        claim_ids=[],
        concept_status="verified",
        evidence_refs=["ev_001"],
        evidence_statuses=["active"],
        source_trust_statuses=["accepted"],
        synthesis_provenance={"method": "merge"},
        derived_from=[],
        review_status="pending",
    )

    report = check_default_closure(obj, _passing_integrity_report(obj.id))

    assert report.passed is False
    assert _check(report, "synthesized_full_provenance").details == "missing_provenance"
    _assert_no_assumed_details(report)


def test_non_publishable_dependency_fails_closed() -> None:
    obj = SimpleNamespace(
        id="ko-bad-dependency",
        status="verified",
        knowledge_mode="observed",
        claim_ids=[],
        concept_status="verified",
        evidence_refs=["ev_001"],
        evidence_statuses=["active"],
        source_trust_statuses=["rejected"],
    )

    report = check_default_closure(obj, _passing_integrity_report(obj.id))

    assert report.passed is False
    assert _check(report, "all_source_trust_accepted").details == "dependency_not_publishable"
    _assert_no_assumed_details(report)
