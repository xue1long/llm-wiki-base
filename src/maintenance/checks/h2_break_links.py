"""H2: Wikilinks + relations resolve to existing wiki pages."""
import re
from pathlib import Path

from ..health_check import Check, CheckIssue, CheckResult, CheckSeverity


WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")


class H2BreakLinksCheck(Check):
    name = "H2"
    description = "All wikilinks and relations resolve to existing wiki pages"

    def run(self) -> CheckResult:
        issues: list[CheckIssue] = []
        stats = {"pages_checked": 0, "links_checked": 0, "broken": 0}

        # Build id → file path map
        id_to_path: dict[str, Path] = {}
        for md_file in self._all_wiki_pages():
            fm, _ = self._load_frontmatter(md_file)
            pid = fm.get("id")
            if pid:
                id_to_path[pid] = md_file

        for md_file in self._all_wiki_pages():
            fm, body = self._load_frontmatter(md_file)
            page_id = fm.get("id", md_file.stem)
            stats["pages_checked"] += 1

            for match in WIKILINK_RE.finditer(body):
                target = match.group(1).strip()
                stats["links_checked"] += 1
                if target not in id_to_path and not self._is_intentional_stub(target):
                    if not self._resolve_via_aliases(target, id_to_path):
                        issues.append(CheckIssue(
                            severity=CheckSeverity.ERROR,
                            code="H2-BROKEN-WIKILINK",
                            message=f"Wikilink target not found: {target}",
                            page_id=page_id,
                            target=target,
                        ))
                        stats["broken"] += 1

            for relation in fm.get("relations", []):
                if not isinstance(relation, dict):
                    continue
                target = relation.get("target")
                if not target:
                    continue
                stats["links_checked"] += 1
                if target not in id_to_path:
                    if not self._resolve_via_aliases(target, id_to_path):
                        issues.append(CheckIssue(
                            severity=CheckSeverity.ERROR,
                            code="H2-BROKEN-RELATION",
                            message=f"Relation target not found: {target}",
                            page_id=page_id,
                            target=target,
                        ))
                        stats["broken"] += 1

        passed = len([i for i in issues if i.severity == CheckSeverity.ERROR]) == 0
        return CheckResult(
            name=self.name,
            description=self.description,
            passed=passed,
            issue_count=len(issues),
            issues=issues,
            stats=stats,
        )

    def _is_intentional_stub(self, target: str) -> bool:
        stubs_dir = self.project_path / "wiki" / "_stubs"
        return (stubs_dir / f"{target}.md").exists()

    def _resolve_via_aliases(self, target: str, id_to_path: dict) -> bool:
        try:
            from src.wiki import SlugAliasRegistry
            reg = SlugAliasRegistry(str(self.project_path))
            canonical = reg.get_canonical(target)
            return canonical is not None and canonical in id_to_path
        except Exception:
            return False
