# Health Check Design Spec

**Date:** 2026-07-22
**Status:** Approved (pending user sign-off)
**Target codebase:** ruflo-kb (Python 3.11+, master @ 749aa3d, post-Wiki-Fields spec)
**Inspired by:** Novel-Knowledge-Base v3.0 `src/maintenance/health_check.py` (H1-H11)

## Goal

Add a 5-dimension operational health check CLI (`python -m src.cli health`) that scans a project's wiki/ + .index/ + raw/ for common issues:

- **H1** File existence — all referenced wiki files exist on disk
- **H2** Break-links — wikilinks `[[X]]` and relations `target: X` resolve to existing pages
- **H3** Density — no pool/page-type category has > 150 pages
- **H4** ID format — all `id:` fields match UUID v7 + slug format (Wiki Fields spec)
- **H5** Tag namespace — all tags use controlled prefixes (Wiki Fields spec)

Default runs all 5; `--only H1 H3` runs subset; `--skip H5` excludes; `--strict` exits code 1 on any failure (CI-friendly); `--json` outputs machine-readable.

This gives users a single command to validate their wiki integrity, complementing the existing wiki v2.0 lint operation (which focuses on content quality, not structural integrity).

## Non-goals

- H6-H11 from NKB (DB consistency / done ratio / use_context coverage / workflow_state distribution / verified overdue / violation guard) are deferred.
- No automatic repair (just diagnostic).
- No remote monitoring integration (Prometheus metrics spec already covers that).
- No wiki rebuild (separate `cmd_rebuild_index` operation).

## Architecture

```
python -m src.cli health [--only H1,H3] [--skip H5] [--strict] [--json] [--project <id>]
   │
   ▼
HealthCheckRunner.run(ctx, selected_checks, output_format)
   │
   ├── For each check in selected_checks:
   │   check.run(ctx) → CheckResult(passed, issues, stats)
   │
   ├── Aggregate results
   │
   └── Format output (text | json)
       If --strict and any failed → exit code 1

Individual checks:
H1: Scan all wiki/*.md → for each frontmatter `sources:` and `relations:` references
    → verify file/path exists
H2: Scan all wiki/*.md → for each [[wikilink]] + relations.target → resolve to existing page
H3: Group wiki pages by pool + type → count per group → flag groups > 150
H4: For each page, validate `id:` matches ^card_[0-9a-f]{13}_[0-9a-f]{8}_[a-z0-9-]+$
H5: For each page, validate tags against TagNamespace prefixes
```

## Components

### New modules

```
src/maintenance/health_check.py    # HealthCheckRunner + CheckResult + Check base class
src/maintenance/checks/
├── __init__.py
├── base.py                       # Check abstract class
├── h1_file_existence.py
├── h2_break_links.py
├── h3_density.py
├── h4_id_format.py
└── h5_tag_namespace.py
tests/test_maintenance/
├── test_health_check_runner.py
├── test_h1_file_existence.py
├── test_h2_break_links.py
├── test_h3_density.py
├── test_h4_id_format.py
└── test_h5_tag_namespace.py
```

### Modified modules

| Path | Change |
|---|---|
| `src/cli.py` | `health` subcommand dispatch |
| `src/schemas/migrations/v2_1_to_v2_2.py` | (Wiki Fields spec) ID conversion may affect H4 |

## Data structures

```python
# src/maintenance/health_check.py
from enum import Enum
from dataclasses import dataclass, field

class CheckSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

@dataclass
class CheckIssue:
    severity: CheckSeverity
    code: str                                # "H1-MISSING-FILE", "H2-DANGLING-LINK", etc.
    message: str
    page_id: str | None = None
    file_path: str | None = None
    target: str | None = None                # for link issues

@dataclass
class CheckResult:
    name: str                                # "H1" | "H2" | ...
    description: str
    passed: bool
    issue_count: int
    issues: list[CheckIssue] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)   # e.g., {"files_checked": 152}
    duration_ms: float = 0.0

@dataclass
class HealthReport:
    project_id: str
    started_at: int
    finished_at: int
    check_results: dict[str, CheckResult]    # "H1" → CheckResult
    total_issues: int
    total_errors: int
    total_warnings: int
    passed: bool                            # True if no errors

class HealthCheckRunner:
    ALL_CHECKS = {
        "H1": "File existence",
        "H2": "Break-links (wikilinks + relations)",
        "H3": "Density (per pool + type)",
        "H4": "ID format (UUID v7)",
        "H5": "Tag namespace",
    }
    
    def __init__(self, ctx: ProjectContext):
        self.ctx = ctx
        self.checks = {
            "H1": H1FileExistenceCheck(ctx),
            "H2": H2BreakLinksCheck(ctx),
            "H3": H3DensityCheck(ctx),
            "H4": H4IdFormatCheck(ctx),
            "H5": H5TagNamespaceCheck(ctx),
        }
    
    def run(
        self,
        selected: list[str] | None = None,
        skipped: list[str] = [],
    ) -> HealthReport:
        """Run selected checks (default = all). Skip skipped."""
        if selected is None:
            selected = list(self.ALL_CHECKS.keys())
        selected = [s for s in selected if s not in skipped]
        
        results = {}
        for check_id in selected:
            check = self.checks[check_id]
            result = check.run()
            results[check_id] = result
        
        return self._aggregate(results)
    
    def _aggregate(self, results: dict[str, CheckResult]) -> HealthReport:
        total_issues = sum(r.issue_count for r in results.values())
        total_errors = sum(r.issue_count for r in results.values() if r.severity == CheckSeverity.ERROR or any(i.severity == CheckSeverity.ERROR for i in r.issues))
        # ... etc.
        return HealthReport(
            project_id=self.ctx.id,
            passed=total_errors == 0,
            total_issues=total_issues,
            ...
        )
```

```python
# src/maintenance/checks/base.py
from abc import ABC, abstractmethod

class Check(ABC):
    name: str
    description: str
    
    def __init__(self, ctx: ProjectContext):
        self.ctx = ctx
    
    @abstractmethod
    def run(self) -> CheckResult:
        ...
    
    def _all_wiki_pages(self) -> list[Path]:
        """Helper: list all wiki/*.md files."""
        wiki_dir = self.ctx.paths.wiki
        return list(wiki_dir.rglob("*.md"))
    
    def _load_frontmatter(self, path: Path) -> tuple[dict, str]:
        """Helper: parse frontmatter + body."""
        content = path.read_text(encoding="utf-8")
        if not content.startswith("---\n"):
            return {}, content
        end = content.find("\n---", 4)
        if end < 0:
            return {}, content
        fm_text = content[4:end]
        body = content[end + 5:].lstrip("\n")
        try:
            fm = yaml.safe_load(fm_text) or {}
        except yaml.YAMLError:
            return {}, content
        return fm, body
```

```python
# src/maintenance/checks/h1_file_existence.py
class H1FileExistenceCheck(Check):
    name = "H1"
    description = "All files referenced by wiki pages exist on disk"
    
    def run(self) -> CheckResult:
        issues = []
        stats = {"pages_checked": 0, "sources_checked": 0}
        
        for md_file in self._all_wiki_pages():
            fm, _ = self._load_frontmatter(md_file)
            page_id = fm.get("id", md_file.stem)
            stats["pages_checked"] += 1
            
            for source in fm.get("sources", []):
                stats["sources_checked"] += 1
                # source can be: relative path "raw/sources/foo.pdf" or absolute
                if source.startswith("/"):
                    source_path = Path(source)
                else:
                    source_path = self.ctx.path / source
                
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

```python
# src/maintenance/checks/h2_break_links.py
class H2BreakLinksCheck(Check):
    name = "H2"
    description = "All wikilinks and relations.target resolve to existing pages"
    
    def run(self) -> CheckResult:
        # Build page_id → file_path index
        id_to_path = {}
        for md_file in self._all_wiki_pages():
            fm, _ = self._load_frontmatter(md_file)
            if "id" in fm:
                id_to_path[fm["id"]] = md_file
        
        issues = []
        stats = {"pages_checked": 0, "links_checked": 0, "broken": 0}
        
        for md_file in self._all_wiki_pages():
            fm, body = self._load_frontmatter(md_file)
            page_id = fm.get("id", md_file.stem)
            stats["pages_checked"] += 1
            
            # Check wikilinks in body
            wikilink_pattern = re.compile(r"\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]")
            for match in wikilink_pattern.finditer(body):
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
            
            # Check relations.target
            for relation in fm.get("relations", []):
                target = relation.get("target") if isinstance(relation, dict) else None
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
        """Check if target is an intentional stub (wiki/_stubs/...)"""
        return (self.ctx.paths.wiki / "_stubs" / f"{target}.md").exists()
```

```python
# src/maintenance/checks/h3_density.py
class H3DensityCheck(Check):
    name = "H3"
    description = "No pool + page-type category exceeds 150 pages"
    
    DENSITY_LIMIT = 150
    
    def run(self) -> CheckResult:
        # Group by (pool, type)
        from collections import Counter
        counts = Counter()
        for md_file in self._all_wiki_pages():
            fm, _ = self._load_frontmatter(md_file)
            pool = fm.get("pool", "drift")
            ptype = fm.get("type", "unknown")
            counts[(pool, ptype)] += 1
        
        issues = []
        stats = {"categories_checked": len(counts), "over_limit": 0}
        for (pool, ptype), count in sorted(counts.items()):
            if count > self.DENSITY_LIMIT:
                issues.append(CheckIssue(
                    severity=CheckSeverity.WARNING,
                    code="H3-DENSITY-OVER-LIMIT",
                    message=f"pool={pool} type={ptype} has {count} pages (> {self.DENSITY_LIMIT})",
                ))
                stats["over_limit"] += 1
        
        return CheckResult(
            name=self.name,
            description=self.description,
            passed=len(issues) == 0,
            issue_count=len(issues),
            issues=issues,
            stats=stats,
        )
```

```python
# src/maintenance/checks/h4_id_format.py
import re

class H4IdFormatCheck(Check):
    name = "H4"
    description = "All wiki page IDs match UUID v7 format"
    
    ID_PATTERN = re.compile(r"^card_[0-9a-f]{13}_[0-9a-f]{8}_[a-z0-9-]+$")
    
    def run(self) -> CheckResult:
        issues = []
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
                    file_path=str(md_file.relative_to(self.ctx.path)),
                ))
                stats["invalid_ids"] += 1
                continue
            
            if not self.ID_PATTERN.match(page_id):
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
            passed=len(issues) == 0,
            issue_count=len(issues),
            issues=issues,
            stats=stats,
        )
```

```python
# src/maintenance/checks/h5_tag_namespace.py
class H5TagNamespaceCheck(Check):
    name = "H5"
    description = "All wiki page tags use controlled namespace prefixes"
    
    def run(self) -> CheckResult:
        from src.wiki.tag_namespace import TagNamespace
        
        issues = []
        stats = {"pages_checked": 0, "tags_checked": 0, "invalid_tags": 0}
        
        for md_file in self._all_wiki_files():
            fm, _ = self._load_frontmatter(md_file)
            page_id = fm.get("id", md_file.stem)
            stats["pages_checked"] += 1
            
            for tag in fm.get("tags", []):
                stats["tags_checked"] += 1
                if not TagNamespace.is_valid(tag):
                    issues.append(CheckIssue(
                        severity=CheckSeverity.WARNING,
                        code="H5-INVALID-TAG",
                        message=f"Tag '{tag}' does not use a controlled prefix",
                        page_id=page_id,
                        target=tag,
                    ))
                    stats["invalid_tags"] += 1
        
        return CheckResult(
            name=self.name,
            description=self.description,
            passed=len(issues) == 0,
            issue_count=len(issues),
            issues=issues,
            stats=stats,
        )
```

## Output formats

### Text format (default)

```
=== Health Check: research ===

H1: File existence                                       ✅ PASS
    152 pages, 304 sources checked
H2: Break-links (wikilinks + relations)                ⚠️  WARNINGS (3)
    152 pages, 421 links checked
    ⚠️  WARNING  H2-BROKEN-WIKILINK  page=foo  target=missing-bar
        in file: wiki/concepts/foo.md
    ⚠️  WARNING  H2-BROKEN-WIKILINK  page=baz  target=old-name
        in file: wiki/entities/baz.md
    ❌ ERROR     H2-BROKEN-RELATION   page=qux  target=ghost-page
        in file: wiki/concepts/qux.md
H3: Density                                              ✅ PASS
    18 categories checked
H4: ID format (UUID v7)                                 ⚠️  WARNINGS (2)
    152 pages, 2 invalid IDs
    ⚠️  WARNING  H4-INVALID-ID-FORMAT  page=old-id-1
    ⚠️  WARNING  H4-MISSING-ID         file=wiki/misc.md
H5: Tag namespace                                        ✅ PASS
    152 pages, 612 tags checked

─────────────────────────────────────────────
Total: 5 issues (1 error, 4 warnings)
Status: ❌ UNHEALTHY (1 error)
─────────────────────────────────────────────
```

### JSON format

```json
{
  "project_id": "uuid",
  "started_at": 1721558400000,
  "finished_at": 1721558403000,
  "passed": false,
  "total_issues": 5,
  "total_errors": 1,
  "total_warnings": 4,
  "check_results": {
    "H1": {
      "name": "H1",
      "description": "File existence",
      "passed": true,
      "issue_count": 0,
      "issues": [],
      "stats": {"pages_checked": 152, "sources_checked": 304},
      "duration_ms": 12.3
    },
    "H2": {
      "name": "H2",
      "description": "Break-links (wikilinks + relations)",
      "passed": false,
      "issue_count": 3,
      "issues": [
        {
          "severity": "warning",
          "code": "H2-BROKEN-WIKILINK",
          "message": "Wikilink target not found: missing-bar",
          "page_id": "foo",
          "target": "missing-bar"
        },
        ...
      ],
      "stats": {"pages_checked": 152, "links_checked": 421, "broken": 3},
      "duration_ms": 45.6
    },
    ...
  }
}
```

## CLI surface

```
python -m src.cli health [--only H1,H3] [--skip H5] [--strict] [--json] [--project <id>]
    # Default: run all 5 checks; --strict → exit 1 on errors; --json → machine-readable

python -m src.cli health list-checks
    # Print all check IDs + descriptions

python -m src.cli health fix H5 [--dry-run] [--project <id>]
    # Auto-fix invalid tags (suggest prefix; --apply to commit)
    # Future: H2 fix (delete broken wikilinks); H4 fix (regenerate IDs)
```

## HTTP + MCP

```
GET /api/v1/projects/{id}/health?only=H1,H3&skip=H5
    # Returns HealthReport JSON

MCP tools:
ruflo_kb_health(project_id, only=None, skip=None)
    # Returns HealthReport; LLM agent can use to verify wiki integrity before operations
```

## Error handling

| Stage | Error | Strategy |
|---|---|---|
| Check runner | Frontmatter parse error | Skip page; log error in issues; continue |
| Check runner | Wiki page file unreadable | Skip; log warning; continue |
| H1 source path | Path traversal `..` detected | Skip; log security error |
| H2 wikilink | Target on disk but unreadable | Log warning; treat as broken |
| H3 density | Categories > 1000 (extreme case) | Cap at 1000 + warn |
| H4 ID | UUID v7 with non-standard millis prefix | Warn (not error — old wiki pages may exist pre-spec) |
| H5 tag | Tag with unknown prefix but in wiki/_stubs/ | Allow (stubs may have free-form tags) |
| strict mode | Any error severity | Exit code 1 |
| strict mode | Warnings only | Exit code 0 |
| json output | Invalid JSON serializable issue | Skip that issue; log |

## Backwards compatibility

- New `health` subcommand: purely additive.
- Existing `lint` subcommand unchanged (lint = content quality, health = structural integrity).
- Health checks are opt-in via subcommand; existing scripts that don't run `health` work unchanged.
- H4 (ID format) only flags old slug-based IDs as warnings, not errors, so projects on Wiki v2.0 are not blocked.

## Testing strategy

### Unit tests

| Module | Test focus |
|---|---|
| `src/maintenance/checks/h1_file_existence.py` | Missing source files; relative paths; absolute paths |
| `src/maintenance/checks/h2_break_links.py` | Wikilink resolution; relations resolution; intentional stubs |
| `src/maintenance/checks/h3_density.py` | Over-limit detection; multiple categories |
| `src/maintenance/checks/h4_id_format.py` | Valid UUID v7; invalid formats; missing id |
| `src/maintenance/checks/h5_tag_namespace.py` | Valid prefixes; invalid prefixes; empty tags |
| `src/maintenance/health_check.py` | Runner; --only / --skip filtering; aggregation |

### Integration tests

```
tests/test_integration/test_health_e2e.py:
    def test_healthy_project():
        # Create wiki with all valid pages
        # Run health
        # Verify: all checks pass

    def test_broken_links_detected():
        # Create pages with broken [[wikilinks]] + broken relations.target
        # Run health H2
        # Verify: warnings + errors reported with correct target names

    def test_density_over_limit():
        # Create 200 pages in pool_1 type=entity
        # Run health H3
        # Verify: warning with count 200

    def test_id_format_old_slug():
        # Create page with id "old-id-format" (not UUID v7)
        # Run health H4
        # Verify: warning (not error) so projects on v2.0 not blocked

    def test_strict_mode_exit_code():
        # Run health --strict with one error
        # Verify: exit code 1
```

## Implementation order

3 phases:

1. **Foundation + 5 checks** — Check base class + 5 check implementations + tests
2. **Runner + output formats** — HealthCheckRunner + text/JSON output + --only/--skip filtering + tests
3. **CLI + HTTP + MCP** — `cmd_health` + endpoints + tools + integration tests

## Cost estimation

- Each check: O(N pages) scan; ~10ms per 100 pages
- Total for 1000-page wiki: ~500ms
- No LLM calls (pure filesystem inspection)
- New code: ~600 lines + ~300 tests

## Open questions / deferred

- H6-H11 from NKB (DB consistency / done ratio / use_context coverage / workflow_state distribution / verified overdue / violation guard).
- Auto-fix for H2/H4/H5 (currently H5 has a `--fix` hook).
- Parallel check execution (each check is independent).
- Per-check timeout (long-running scans on huge wikis).
- Custom check plugins (user-defined checks).
- Integration with CI / pre-commit (GitHub Actions workflow).