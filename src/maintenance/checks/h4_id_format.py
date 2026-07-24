"""H4: All wiki page IDs match UUID v7 format."""
import re

from ..health_check import Check, CheckIssue, CheckResult, CheckSeverity


# Accepts both UUID v7 (card_<13hex>_<8hex>_<slug>) and legacy pure slug
ID_PATTERN = re.compile(r"^(?:card_[0-9a-f]{13}_[0-9a-f]{8}_[a-z0-9-]+|[a-z0-9-]+)$")


class H4IdFormatCheck(Check):
    name = "H4"
    description = "All wiki page IDs match valid format (UUID v7 or legacy slug)"

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
                    message="Page missing id field",
                    file_path=str(md_file.relative_to(self.project_path)),
                ))
                stats["invalid_ids"] += 1
                continue

            if not ID_PATTERN.match(str(page_id)):
                issues.append(CheckIssue(
                    severity=CheckSeverity.WARNING,
                    code="H4-INVALID-ID-FORMAT",
                    message=f"Page id '{page_id}' does not match UUID v7 format",
                    page_id=str(page_id),
                ))
                stats["invalid_ids"] += 1

        passed = len([i for i in issues if i.severity == CheckSeverity.ERROR]) == 0
        return CheckResult(
            name=self.name,
            description=self.description,
            passed=passed,
            issue_count=len(issues),
            issues=issues,
            stats=stats,
        )
