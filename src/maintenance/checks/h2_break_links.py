"""H2: Wikilinks + relations resolve to existing wiki pages."""
import re
import json
from pathlib import Path

from ..health_check import Check, CheckIssue, CheckResult, CheckSeverity
from src.wiki.features.slug_utils import normalize_reconcile_slug
from src.wiki.features.target_resolver import (
    ResolutionContext,
    is_valid_taxonomy_target,
    resolve_wiki_target,
)


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

        title_index: dict[str, list[str]] = {}
        for pid, md_file in id_to_path.items():
            fm, _ = self._load_frontmatter(md_file)
            title = str(fm.get("title") or "").strip()
            if title:
                title_index.setdefault(normalize_reconcile_slug(title), []).append(pid)
        try:
            from src.wiki import SlugAliasRegistry
            aliases = SlugAliasRegistry(str(self.project_path)).aliases
        except Exception:
            aliases = {}
        resolution_context = ResolutionContext(
            existing_index=frozenset(normalize_reconcile_slug(pid) for pid in id_to_path),
            title_index=title_index,
            aliases=aliases,
        )

        for md_file in self._all_wiki_pages():
            fm, body = self._load_frontmatter(md_file)
            page_id = fm.get("id", md_file.stem)
            stats["pages_checked"] += 1

            for match in WIKILINK_RE.finditer(body):
                target = match.group(1).strip()
                stats["links_checked"] += 1
                if not self._resolves(target, resolution_context, id_to_path):
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
                target = relation.get("target") or relation.get("target_id")
                if not target:
                    continue
                stats["links_checked"] += 1
                if not self._resolves(target, resolution_context, id_to_path):
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

    def _resolves(self, target: str, context: ResolutionContext,
                  id_to_path: dict[str, Path]) -> bool:
        if target in id_to_path or self._is_intentional_stub(target):
            return True
        if is_valid_taxonomy_target(target, self.project_path):
            return True
        return resolve_wiki_target(target, context=context).canonical_target is not None

    def _is_intentional_stub(self, target: str) -> bool:
        stubs_dir = self.project_path / "wiki" / "_stubs"
        if (stubs_dir / f"{target}.md").exists():
            return True
        gap_file = self.project_path / ".index" / "migration-support" / "wikilink-gaps.json"
        try:
            gaps = json.loads(gap_file.read_text(encoding="utf-8"))
            return target in set(gaps.get("targets", []))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return False

    def _resolve_via_aliases(self, target: str, id_to_path: dict) -> bool:
        try:
            from src.wiki import SlugAliasRegistry
            reg = SlugAliasRegistry(str(self.project_path))
            canonical = reg.get_canonical(target)
            return canonical is not None and canonical in id_to_path
        except Exception:
            return False
