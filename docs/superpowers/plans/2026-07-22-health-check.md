# Health Check (MVP) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** 5-dimension operational health check CLI for wiki structural integrity. MVP scope: 3 of 5 checks (H1 / H2 / H4); H3 + H5 land in v2.0.1.

**Architecture:** `Check` ABC + `HealthCheckRunner` + 3 check implementations. Text + JSON output formats. `--strict` exits 1 on errors.

**Tech Stack:** Python 3.11+, dataclasses, regex, pathlib, yaml.

**MVP Scope** (per spec): H1 (file existence) + H2 (break-links) + H4 (ID format); text + JSON output; `--strict` / `--only` / `--skip` flags.

---

## Phase 1: Foundation

### Task 1: `src/maintenance/health_check.py` — base classes

**Files:**
- Create: `src/maintenance/__init__.py`
- Create: `src/maintenance/checks/__init__.py`
- Create: `src/maintenance/health_check.py`
- Test: `tests/test_maintenance/test_health_check.py`

- [ ] **Step 1: Write test**

```python
# tests/test_maintenance/test_health_check.py
from src.maintenance.health_check import (
    CheckSeverity, CheckIssue, CheckResult, HealthReport, HealthCheckRunner,
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
        issues=[CheckIssue(severity=CheckSeverity.ERROR, code="X", message="y")]
    )
    assert not r.passed


def test_health_report_aggregates():
    r1 = CheckResult(name="H1", description="d", passed=True, issue_count=0)
    r2 = CheckResult(name="H2", description="d", passed=False, issue_count=1,
                    issues=[CheckIssue(severity=CheckSeverity.ERROR, code="X", message="y")])
    report = HealthReport(
        project_id="uuid", started_at=1000, finished_at=2000,
        check_results={"H1": r1, "H2": r2},
    )
    assert report.total_issues == 1
    assert report.total_errors == 1
    assert not report.passed
```

- [ ] **Step 2: Run test**

`pytest tests/test_maintenance/test_health_check.py -v` → FAIL

- [ ] **Step 3: Implement**

```python
# src/maintenance/__init__.py
"""Operational maintenance (health checks, etc.)."""
```

```python
# src/maintenance/checks/__init__.py
"""Individual health checks (H1 / H2 / H3 / H4 / H5)."""
```

```python
# src/maintenance/health_check.py
"""Health check framework — structural integrity checks for ruflo-kb wiki.

Provides Check ABC + CheckResult / HealthReport dataclasses + HealthCheckRunner
that aggregates check results and produces text/JSON output.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING


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


class Check(ABC):
    """Base class for individual health checks."""

    name: str = ""
    description: str = ""

    def __init__(self, project_path):
        self.project_path = project_path

    @abstractmethod
    def run(self) -> CheckResult: ...

    def _all_wiki_pages(self):
        from pathlib import Path
        wiki_dir = self.project_path / "wiki"
        if not wiki_dir.exists():
            return []
        return list(wiki_dir.rglob("*.md"))

    def _load_frontmatter(self, path) -> tuple[dict, str]:
        import yaml
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            return {}, text
        end = text.find("\n---", 4)
        if end < 0:
            return {}, text
        fm_text = text[4:end]
        body = text[end + 5:].lstrip("\n")
        try:
            fm = yaml.safe_load(fm_text) or {}
        except yaml.YAMLError:
            return {}, text
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
        from time import time
        started = int(time() * 1000)
        skipped = skipped or []
        checks_to_run = [c for c in (selected or list(self.checks.keys())) if c not in skipped]

        results: dict[str, CheckResult] = {}
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
```

- [ ] **Step 4: Run test**

`pytest tests/test_maintenance/test_health_check.py -v` → PASS (5/5)

- [ ] **Step 5: Commit**

```bash
git add src/maintenance/ tests/test_maintenance/
git commit -m "feat(maintenance): add HealthCheck base classes (Check, CheckResult, HealthReport)"
```

---

## Phase 2: Individual checks (Tasks 2-4 parallel)

### Task 2: H1 File existence check

**Files:**
- Create: `src/maintenance/checks/h1_file_existence.py`
- Test: `tests/test_maintenance/test_h1_file_existence.py`

- [ ] **Step 1: Write test**

```python
# tests/test_maintenance/test_h1_file_existence.py
from pathlib import Path

from src.maintenance.checks.h1_file_existence import H1FileExistenceCheck
from src.maintenance.health_check import CheckSeverity


def test_h1_passes_when_all_sources_exist(tmp_path):
    (tmp_path / "raw" / "sources").mkdir(parents=True)
    (tmp_path / "raw" / "sources" / "foo.pdf").write_bytes(b"x")
    (tmp_path / "wiki" / "sources").mkdir(parents=True)
    (tmp_path / "wiki" / "sources" / "foo.md").write_text(
        "---\nid: foo\nsources: [raw/sources/foo.pdf]\n---\nbody\n",
        encoding="utf-8"
    )

    check = H1FileExistenceCheck(tmp_path)
    result = check.run()

    assert result.passed
    assert result.issue_count == 0
    assert result.stats["pages_checked"] == 1
    assert result.stats["sources_checked"] == 1


def test_h1_fails_on_missing_source(tmp_path):
    (tmp_path / "raw" / "sources").mkdir(parents=True)
    (tmp_path / "wiki" / "sources").mkdir(parents=True)
    (tmp_path / "wiki" / "sources" / "foo.md").write_text(
        "---\nid: foo\nsources: [raw/sources/missing.pdf]\n---\nbody\n",
        encoding="utf-8"
    )

    check = H1FileExistenceCheck(tmp_path)
    result = check.run()

    assert not result.passed
    assert result.issue_count == 1
    issue = result.issues[0]
    assert issue.severity == CheckSeverity.ERROR
    assert issue.code == "H1-MISSING-FILE"
    assert "raw/sources/missing.pdf" in issue.message


def test_h1_absolute_paths_checked(tmp_path):
    (tmp_path / "wiki" / "sources").mkdir(parents=True)
    (tmp_path / "wiki" / "sources" / "abs.md").write_text(
        f"---\nid: abs\nsources: [{tmp_path}/external.pdf]\n---\nbody\n",
        encoding="utf-8"
    )

    check = H1FileExistenceCheck(tmp_path)
    result = check.run()
    # Absolute path doesn't exist
    assert not result.passed
```

- [ ] **Step 2: Run test**

`pytest tests/test_maintenance/test_h1_file_existence.py -v` → FAIL

- [ ] **Step 3: Implement**

```python
# src/maintenance/checks/h1_file_existence.py
"""H1: All files referenced by wiki pages exist on disk."""
from pathlib import Path

from ..health_check import Check, CheckIssue, CheckResult, CheckSeverity


class H1FileExistenceCheck(Check):
    name = "H1"
    description = "All files referenced by wiki pages exist on disk"

    def run(self) -> CheckResult:
        issues: list[CheckIssue] = []
        stats = {"pages_checked": 0, "sources_checked": 0}

        for md_file in self._all_wiki_pages():
            fm, _ = self._load_frontmatter(md_file)
            page_id = fm.get("id", md_file.stem)
            stats["pages_checked"] += 1

            for source in fm.get("sources", []):
                stats["sources_checked"] += 1
                if source.startswith("/"):
                    source_path = Path(source)
                else:
                    source_path = self.project_path / source
                if not source_path.exists():
                    issues.append(CheckIssue(
                        severity=CheckSeverity.ERROR,
                        code="H1-MISSING-FILE",
                        message=f"Source file not found: {source}",
                        page_id=page_id,
                        target=source,
                    ))

        return CheckResult(
            name=self.name,
            description=self.description,
            passed=len(issues) == 0,
            issue_count=len(issues),
            issues=issues,
            stats=stats,
        )
```

- [ ] **Step 4: Run test**

`pytest tests/test_maintenance/test_h1_file_existence.py -v` → PASS (3/3)

- [ ] **Step 5: Commit**

```bash
git add src/maintenance/checks/h1_file_existence.py tests/test_maintenance/test_h1_file_existence.py
git commit -m "feat(maintenance): add H1 file existence check"
```

---

### Task 3: H2 Break-links check

**Files:**
- Create: `src/maintenance/checks/h2_break_links.py`
- Test: `tests/test_maintenance/test_h2_break_links.py`

- [ ] **Step 1: Write test**

```python
# tests/test_maintenance/test_h2_break_links.py
import re
from pathlib import Path

from src.maintenance.checks.h2_break_links import H2BreakLinksCheck
from src.maintenance.health_check import CheckSeverity


def test_h2_passes_when_all_wikilinks_resolve(tmp_path):
    (tmp_path / "wiki" / "entities").mkdir(parents=True)
    (tmp_path / "wiki" / "entities" / "foo.md").write_text("---\nid: foo\n---\nbody", encoding="utf-8")
    (tmp_path / "wiki" / "entities" / "bar.md").write_text(
        "---\nid: bar\n---\nsee [[foo]]\n", encoding="utf-8"
    )

    check = H2BreakLinksCheck(tmp_path)
    result = check.run()
    assert result.passed
    assert result.issue_count == 0


def test_h2_flags_broken_wikilink(tmp_path):
    (tmp_path / "wiki" / "entities").mkdir(parents=True)
    (tmp_path / "wiki" / "entities" / "foo.md").write_text(
        "---\nid: foo\n---\nsee [[missing-page]]\n", encoding="utf-8"
    )

    check = H2BreakLinksCheck(tmp_path)
    result = check.run()
    assert not result.passed
    issue = result.issues[0]
    assert issue.code == "H2-BROKEN-WIKILINK"
    assert issue.target == "missing-page"


def test_h2_flags_broken_relation(tmp_path):
    (tmp_path / "wiki" / "entities").mkdir(parents=True)
    (tmp_path / "wiki" / "entities" / "foo.md").write_text(
        "---\nid: foo\nrelations:\n  - target: ghost\n    type: references\n---\nbody",
        encoding="utf-8"
    )

    check = H2BreakLinksCheck(tmp_path)
    result = check.run()
    assert not result.passed
    issue = result.issues[0]
    assert issue.code == "H2-BROKEN-RELATION"


def test_h2_intentional_stub_not_broken(tmp_path):
    """Wikilink to wiki/_stubs/ is intentional, not a broken link."""
    (tmp_path / "wiki" / "entities").mkdir(parents=True)
    (tmp_path / "wiki" / "_stubs").mkdir(parents=True)
    (tmp_path / "wiki" / "_stubs" / "pending.md").write_text(
        "---\nid: pending\ntype: stub\n---\nstub", encoding="utf-8"
    )
    (tmp_path / "wiki" / "entities" / "foo.md").write_text(
        "---\nid: foo\n---\nsee [[pending]]\n", encoding="utf-8"
    )

    check = H2BreakLinksCheck(tmp_path)
    result = check.run()
    assert result.passed
```

- [ ] **Step 2: Run test**

`pytest tests/test_maintenance/test_h2_break_links.py -v` → FAIL

- [ ] **Step 3: Implement**

```python
# src/maintenance/checks/h2_break_links.py
"""H2: All wikilinks [[X]] and relations.target resolve to existing pages."""
import re

from ..health_check import Check, CheckIssue, CheckResult, CheckSeverity


WIKILINK_PATTERN = re.compile(r"\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]")


class H2BreakLinksCheck(Check):
    name = "H2"
    description = "All wikilinks and relations.target resolve to existing pages"

    def run(self) -> CheckResult:
        issues: list[CheckIssue] = []
        stats = {"pages_checked": 0, "links_checked": 0, "broken": 0}

        # Build id → file index
        id_to_path: dict[str, Path] = {}
        for md_file in self._all_wiki_pages():
            fm, _ = self._load_frontmatter(md_file)
            if "id" in fm:
                id_to_path[fm["id"]] = md_file

        for md_file in self._all_wiki_pages():
            fm, body = self._load_frontmatter(md_file)
            page_id = fm.get("id", md_file.stem)
            stats["pages_checked"] += 1

            # Wikilinks
            for match in WIKILINK_PATTERN.finditer(body):
                target = match.group(1).strip()
                stats["links_checked"] += 1
                if target not in id_to_path and not self._is_intentional_stub(target):
                    issues.append(CheckIssue(
                        severity=CheckSeverity.WARNING,
                        code="H2-BROKEN-WIKILINK",
                        message=f"Wikilink target not found: {target}",
                        page_id=page_id,
                        target=target,
                    ))
                    stats["broken"] += 1

            # Relations
            for relation in fm.get("relations", []):
                if not isinstance(relation, dict):
                    continue
                target = relation.get("target")
                if not target:
                    continue
                stats["links_checked"] += 1
                if target not in id_to_path:
                    issues.append(CheckIssue(
                        severity=CheckSeverity.ERROR,
                        code="H2-BROKEN-RELATION",
                        message=f"Relation target not found: {target}",
                        page_id=page_id,
                        target=target,
                    ))
                    stats["broken"] += 1

        return CheckResult(
            name=self.name,
            description=self.description,
            passed=len([i for i in issues if i.severity == CheckSeverity.ERROR]) == 0,
            issue_count=len(issues),
            issues=issues,
            stats=stats,
        )

    def _is_intentional_stub(self, target: str) -> bool:
        stubs_dir = self.project_path / "wiki" / "_stubs"
        return (stubs_dir / f"{target}.md").exists()
```

- [ ] **Step 4: Run test**

`pytest tests/test_maintenance/test_h2_break_links.py -v` → PASS (4/4)

- [ ] **Step 5: Commit**

```bash
git add src/maintenance/checks/h2_break_links.py tests/test_maintenance/test_h2_break_links.py
git commit -m "feat(maintenance): add H2 break-links check (wikilinks + relations)"
```

---

### Task 4: H4 ID format check

**Files:**
- Create: `src/maintenance/checks/h4_id_format.py`
- Test: `tests/test_maintenance/test_h4_id_format.py`

- [ ] **Step 1: Write test**

```python
# tests/test_maintenance/test_h4_id_format.py
from pathlib import Path

from src.maintenance.checks.h4_id_format import H4IdFormatCheck
from src.maintenance.health_check import CheckSeverity


def test_h4_passes_for_valid_uuid_v7_ids(tmp_path):
    (tmp_path / "wiki" / "entities").mkdir(parents=True)
    (tmp_path / "wiki" / "entities" / "a.md").write_text(
        "---\nid: card_018f3a8e2b1c4_a3f9d12c_lin-feng\n---\nbody",
        encoding="utf-8"
    )

    check = H4IdFormatCheck(tmp_path)
    result = check.run()
    assert result.passed
    assert result.issue_count == 0


def test_h4_warns_on_old_slug_format(tmp_path):
    (tmp_path / "wiki" / "entities").mkdir(parents=True)
    (tmp_path / "wiki" / "entities" / "a.md").write_text(
        "---\nid: lin-feng\n---\nbody",
        encoding="utf-8"
    )

    check = H4IdFormatCheck(tmp_path)
    result = check.run()
    # Warning (not error) for backwards compat
    assert result.passed   # warnings don't fail
    assert result.issue_count == 1
    assert result.issues[0].code == "H4-INVALID-ID-FORMAT"


def test_h4_errors_on_missing_id(tmp_path):
    (tmp_path / "wiki" / "entities").mkdir(parents=True)
    (tmp_path / "wiki" / "entities" / "a.md").write_text(
        "---\ntitle: no id\n---\nbody",
        encoding="utf-8"
    )

    check = H4IdFormatCheck(tmp_path)
    result = check.run()
    assert not result.passed
    assert result.issues[0].code == "H4-MISSING-ID"
```

- [ ] **Step 2: Run test**

`pytest tests/test_maintenance/test_h4_id_format.py -v` → FAIL

- [ ] **Step 3: Implement**

```python
# src/maintenance/checks/h4_id_format.py
"""H4: All wiki page IDs match UUID v7 format (card_<13hex>_<8hex>_<slug>)."""
import re

from ..health_check import Check, CheckIssue, CheckResult, CheckSeverity


# UUID v7 format: card_<13hex_millis>_<8hex_random>_<slug>
# Slug: kebab-case, [a-z0-9-]+
ID_PATTERN = re.compile(r"^card_[0-9a-f]{13}_[0-9a-f]{8}_[a-z0-9-]+$")


class H4IdFormatCheck(Check):
    name = "H4"
    description = "All wiki page IDs match UUID v7 format"

    def run(self) -> CheckResult:
        issues: list[CheckIssue] = []
        stats = {"pages_checked": 0, "invalid_ids": 0}

        for md_file in self._all_wiki_pages():
            fm, _ = self._load_frontmatter(md_file)
            page_id = fm.get("id")
            stats["pages_checked"] += 1

            if not page_id:
                issues.append(CheckIssue(
                    severity=CheckSeverity.ERROR,
                    code="H4-MISSING-ID",
                    message=f"Page missing id field",
                    file_path=str(md_file.relative_to(self.project_path)),
                ))
                stats["invalid_ids"] += 1
                continue

            if not ID_PATTERN.match(page_id):
                issues.append(CheckIssue(
                    severity=CheckSeverity.WARNING,
                    code="H4-INVALID-ID-FORMAT",
                    message=f"Page id '{page_id}' does not match UUID v7 format",
                    page_id=page_id,
                ))
                stats["invalid_ids"] += 1

        return CheckResult(
            name=self.name,
            description=self.description,
            passed=len([i for i in issues if i.severity == CheckSeverity.ERROR]) == 0,
            issue_count=len(issues),
            issues=issues,
            stats=stats,
        )
```

- [ ] **Step 4: Run test**

`pytest tests/test_maintenance/test_h4_id_format.py -v` → PASS (3/3)

- [ ] **Step 5: Commit**

```bash
git add src/maintenance/checks/h4_id_format.py tests/test_maintenance/test_h4_id_format.py
git commit -m "feat(maintenance): add H4 ID format check (UUID v7)"
```

---

## Phase 3: CLI integration

### Task 5: `src/cli_ext/health_cmd.py` — CLI subcommand

**Files:**
- Create: `src/cli_ext/health_cmd.py`
- Modify: `src/cli.py` (wire subparser)
- Test: `tests/test_cli_ext/test_cmd_health.py`

- [ ] **Step 1: Write test**

```python
# tests/test_cli_ext/test_cmd_health.py
import json
from pathlib import Path

from src.cli_ext.health_cmd import cmd_health
from src.maintenance.health_check import HealthCheckRunner
from src.maintenance.checks.h1_file_existence import H1FileExistenceCheck
from src.maintenance.checks.h2_break_links import H2BreakLinksCheck
from src.maintenance.checks.h4_id_format import H4IdFormatCheck


def test_cmd_health_text_output(tmp_path, capsys):
    """health (default: all checks) → text output."""
    (tmp_path / "wiki" / "sources").mkdir(parents=True)
    (tmp_path / "wiki" / "sources" / "a.md").write_text(
        "---\nid: card_018f3a8e2b1c4_a3f9d12c_a\n---\nbody", encoding="utf-8"
    )
    (tmp_path / "raw" / "sources").mkdir(parents=True)
    (tmp_path / "raw" / "sources" / "a.pdf").write_bytes(b"x")

    args = type("Args", (), {
        "only": None, "skip": None, "strict": False, "json": False, "project": str(tmp_path)
    })()
    cmd_health(args)

    out = capsys.readouter().out
    assert "H1" in out
    assert "✅" in out or "PASS" in out


def test_cmd_health_json_output(tmp_path, capsys):
    """health --json → machine-readable JSON."""
    (tmp_path / "wiki" / "sources").mkdir(parents=True)
    (tmp_path / "wiki" / "sources" / "a.md").write_text(
        "---\nid: card_018f3a8e2b1c4_a3f9d12c_a\n---\nbody", encoding="utf-8"
    )

    args = type("Args", (), {
        "only": None, "skip": None, "strict": False, "json": True, "project": str(tmp_path)
    })()
    cmd_health(args)

    out = capsys.readouter().out
    data = json.loads(out)
    assert "check_results" in data
    assert "H1" in data["check_results"]


def test_cmd_health_strict_exits_1_on_error(tmp_path):
    """health --strict with errors → exit code 1."""
    (tmp_path / "wiki" / "sources").mkdir(parents=True)
    (tmp_path / "wiki" / "sources" / "a.md").write_text(
        "---\nid: card_018f3a8e2b1c4_a3f9d12c_a\nsources: [raw/sources/missing.pdf]\n---\nbody",
        encoding="utf-8"
    )

    import pytest
    args = type("Args", (), {
        "only": None, "skip": None, "strict": True, "json": False, "project": str(tmp_path)
    })()
    with pytest.raises(SystemExit) as exc:
        cmd_health(args)
    assert exc.value.code == 1


def test_cmd_health_only_flag(tmp_path, capsys):
    """health --only H1 runs only H1."""
    (tmp_path / "wiki" / "sources").mkdir(parents=True)
    (tmp_path / "wiki" / "sources" / "a.md").write_text(
        "---\nid: card_018f3a8e2b1c4_a3f9d12c_a\n---\nbody [[ghost]]", encoding="utf-8"
    )

    args = type("Args", (), {
        "only": ["H1"], "skip": None, "strict": False, "json": False, "project": str(tmp_path)
    })()
    cmd_health(args)

    out = capsys.readouter().out
    # Only H1 in output
    assert "H1" in out
    assert "H2" not in out
    assert "H4" not in out
```

- [ ] **Step 2: Run test**

`pytest tests/test_cli_ext/test_cmd_health.py -v` → FAIL

- [ ] **Step 3: Implement**

```python
# src/cli_ext/health_cmd.py
"""Health check CLI subcommand."""
import argparse
import json
import sys
from pathlib import Path

from ..maintenance.health_check import (
    CheckResult,
    CheckSeverity,
    HealthCheckRunner,
)
from ..maintenance.checks.h1_file_existence import H1FileExistenceCheck
from ..maintenance.checks.h2_break_links import H2BreakLinksCheck
from ..maintenance.checks.h4_id_format import H4IdFormatCheck


CHECKS_AVAILABLE = {"H1", "H2", "H3", "H4", "H5"}


def cmd_health(args: argparse.Namespace) -> None:
    """Run wiki structural integrity checks."""
    project_path = Path(args.project)
    if not project_path.exists():
        print(f"Project path not found: {project_path}", file=sys.stderr)
        sys.exit(2)

    selected = args.only or list(CHECKS_AVAILABLE)
    skipped = args.skip or []

    runner = HealthCheckRunner(project_path=project_path, project_id=args.project)
    runner.register("H1", H1FileExistenceCheck(project_path))
    runner.register("H2", H2BreakLinksCheck(project_path))
    runner.register("H4", H4IdFormatCheck(project_path))
    # H3 and H5 not in MVP

    report = runner.run(selected=selected, skipped=skipped)

    if args.json:
        print(json.dumps(_report_to_dict(report), indent=2, ensure_ascii=False))
    else:
        _print_text_report(report)

    if args.strict and not report.passed:
        sys.exit(1)


def _print_text_report(report) -> None:
    for check_id, result in report.check_results.items():
        if result.passed and result.issue_count == 0:
            icon = "✅"
        elif result.passed:
            icon = "⚠️ "
        else:
            icon = "❌"
        print(f"{icon} {check_id}: {result.description}  ({result.issue_count} issues, {result.duration_ms:.1f}ms)")
        for stat, val in result.stats.items():
            print(f"    {stat}: {val}")
        for issue in result.issues:
            print(f"    [{issue.severity.value}] {issue.code}: {issue.message}")
    print()
    total_status = "✅ HEALTHY" if report.passed else "❌ UNHEALTHY"
    print(f"Total: {report.total_issues} issues ({report.total_errors} errors, {report.total_warnings} warnings)")
    print(f"Status: {total_status}")


def _report_to_dict(report) -> dict:
    return {
        "project_id": report.project_id,
        "started_at": report.started_at,
        "finished_at": report.finished_at,
        "passed": report.passed,
        "total_issues": report.total_issues,
        "total_errors": report.total_errors,
        "total_warnings": report.total_warnings,
        "check_results": {
            cid: {
                "name": r.name,
                "description": r.description,
                "passed": r.passed,
                "issue_count": r.issue_count,
                "issues": [
                    {
                        "severity": i.severity.value,
                        "code": i.code,
                        "message": i.message,
                        "page_id": i.page_id,
                        "file_path": i.file_path,
                        "target": i.target,
                    }
                    for i in r.issues
                ],
                "stats": r.stats,
                "duration_ms": r.duration_ms,
            }
            for cid, r in report.check_results.items()
        },
    }
```

- [ ] **Step 4: Wire in `src/cli.py`**

```python
# src/cli.py — add to main():

p_health = subparsers.add_parser("health", help="Run wiki health checks")
p_health.add_argument("--only", nargs="*", help="Run only these checks (e.g., H1 H3)")
p_health.add_argument("--skip", nargs="*", help="Skip these checks")
p_health.add_argument("--strict", action="store_true", help="Exit 1 on any error")
p_health.add_argument("--json", action="store_true", help="JSON output")
p_health.add_argument("--project", help="Project path (default: CWD upward search)")
p_health.set_defaults(func=cmd_health)
```

(Add `from cli_ext.health_cmd import cmd_health` at top.)

- [ ] **Step 5: Run test**

`pytest tests/test_cli_ext/test_cmd_health.py -v` → PASS (4/4)

- [ ] **Step 6: Commit**

```bash
git add src/cli_ext/health_cmd.py src/cli.py tests/test_cli_ext/test_cmd_health.py
git commit -m "feat(cli): add 'health' subcommand (H1 + H2 + H4 MVP)"
```

---

## Self-Review

- [x] Spec coverage: H1 ✓ H2 ✓ H4 ✓ text + JSON output ✓ --only/--skip/--strict ✓
- [x] No placeholders
- [x] Type consistency: `CheckResult.passed = errors == 0`; `HealthReport.total_*` aggregated correctly
- [x] H4 backward compat: old slug-based IDs flagged as warning (not error) so Wiki v2.0 projects not blocked

## Implementation order

Tasks 1-4 parallel (no inter-deps). Task 5 chains. Total: 5 tasks, ~1-1.5 hours.