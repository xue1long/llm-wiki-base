"""Tests for the health-check framework primitives."""
from src.maintenance.health_check import (
    CheckSeverity, CheckIssue, CheckResult, HealthReport,
)


def test_check_severity_values():
    assert CheckSeverity.ERROR == "error"
    assert CheckSeverity.WARNING == "warning"
    assert CheckSeverity.INFO == "info"


def test_check_issue_construction():
    issue = CheckIssue(
        severity=CheckSeverity.ERROR,
        code="H1-MISSING-FILE",
        message="file not found",
        page_id="abc",
        target="raw/sources/foo.pdf",
    )
    assert issue.severity == CheckSeverity.ERROR
    assert issue.code == "H1-MISSING-FILE"
    assert issue.page_id == "abc"


def test_check_result_passed_when_no_issues():
    r = CheckResult(name="H1", description="d", passed=True, issue_count=0)
    assert r.passed


def test_check_result_failed_when_issues():
    r = CheckResult(
        name="H1", description="d", passed=False, issue_count=1,
        issues=[CheckIssue(severity=CheckSeverity.ERROR, code="X", message="y")],
    )
    assert not r.passed


def test_health_report_aggregates():
    r1 = CheckResult(name="H1", description="d", passed=True, issue_count=0)
    r2 = CheckResult(
        name="H2", description="d", passed=False, issue_count=1,
        issues=[CheckIssue(severity=CheckSeverity.ERROR, code="X", message="y")],
    )
    report = HealthReport(
        project_id="uuid", started_at=1000, finished_at=2000,
        check_results={"H1": r1, "H2": r2},
    )
    assert report.total_issues == 1
    assert report.total_errors == 1
    assert not report.passed
