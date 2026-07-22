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
                if not isinstance(source, str):
                    continue
                stats["sources_checked"] += 1
                if source.startswith("/") or (len(source) >= 2 and source[1] == ":"):
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
