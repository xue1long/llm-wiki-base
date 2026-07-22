"""Health check framework — structural integrity checks for ruflo-kb wiki.

Provides Check ABC + CheckResult / HealthReport dataclasses + HealthCheckRunner
that aggregates check results and produces text/JSON output.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from time import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


class CheckSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class CheckIssue:
    severity: CheckSeverity
    code: str                          # e.g., "H1-MISSING-FILE"
    message: str
    page_id: str | None = None
    file_path: str | None = None
    target: str | None = None          # for link issues


@dataclass
class CheckResult:
    name: str
    description: str
    passed: bool
    issue_count: int
    issues: list[CheckIssue] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)
    duration_ms: float = 0.0


@dataclass
class HealthReport:
    project_id: str
    started_at: int
    finished_at: int
    check_results: dict[str, CheckResult]   # "H1" → result
    total_issues: int = 0
    total_errors: int = 0
    total_warnings: int = 0
    passed: bool = True

    def __post_init__(self):
        """Aggregate totals from check_results so manual construction is valid too."""
        if not self.check_results:
            return
        for r in self.check_results.values():
            self.total_issues += r.issue_count
            for issue in r.issues:
                if issue.severity == CheckSeverity.ERROR:
                    self.total_errors += 1
                elif issue.severity == CheckSeverity.WARNING:
                    self.total_warnings += 1
        if self.total_errors == 0 and self.passed is True:
            # Already True by default; explicit assignment for clarity.
            self.passed = True
        else:
            self.passed = self.total_errors == 0


class Check(ABC):
    """Base class for individual health checks."""

    name: str = ""
    description: str = ""

    def __init__(self, project_path):
        self.project_path = project_path

    @abstractmethod
    def run(self) -> CheckResult: ...

    def _all_wiki_pages(self):
        wiki_dir = self.project_path / "wiki"
        if not wiki_dir.exists():
            return []
        return list(wiki_dir.rglob("*.md"))

    def _load_frontmatter(self, path):
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            return {}, text
        end = text.find("\n---", 4)
        if end < 0:
            return {}, text
        fm_text = text[4:end]
        body = text[end + 5:].lstrip("\n")
        try:
            import yaml
            fm = yaml.safe_load(fm_text) or {}
        except Exception:
            fm = {}
        return fm, body


class HealthCheckRunner:
    """Runs selected health checks and aggregates results."""

    def __init__(self, project_path, project_id: str = "default"):
        self.project_path = project_path
        self.project_id = project_id
        self.checks: dict[str, Check] = {}

    def register(self, check_id: str, check: Check) -> None:
        self.checks[check_id] = check

    def run(
        self,
        selected: list[str] | None = None,
        skipped: list[str] | None = None,
    ) -> HealthReport:
        skipped = skipped or []
        checks_to_run = [c for c in (selected or list(self.checks.keys())) if c not in skipped]

        results: dict[str, CheckResult] = {}
        started = int(time() * 1000)
        for check_id in checks_to_run:
            check = self.checks[check_id]
            t0 = time()
            result = check.run()
            result.duration_ms = (time() - t0) * 1000
            results[check_id] = result
        finished = int(time() * 1000)

        report = HealthReport(
            project_id=self.project_id,
            started_at=started,
            finished_at=finished,
            check_results=results,
        )
        for r in results.values():
            report.total_issues += r.issue_count
            for issue in r.issues:
                if issue.severity == CheckSeverity.ERROR:
                    report.total_errors += 1
                elif issue.severity == CheckSeverity.WARNING:
                    report.total_warnings += 1
        report.passed = report.total_errors == 0
        return report
