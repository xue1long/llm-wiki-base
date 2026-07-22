"""Wiki lint (A4) — runs 5 non-LLM checks across all wiki pages.

Detects: LINT-MISSING-ID, LINT-MISSING-TITLE, LINT-EMPTY-BODY, LINT-ORPHAN,
LINT-DUPLICATE. See LintSeverity for severities and LintIssue / LintReport
for the report shape. Public entry point is ``lint_wiki``.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from ..storage.ensure import ensure_knowledge_base
from .indexer import read_index
from ..storage.page_writer import read_page
from ..core.paths import WikiPaths


class LintSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class LintIssue:
    code: str
    severity: LintSeverity
    message: str
    page_id: str | None = None
    suggestion: str | None = None


@dataclass
class LintReport:
    project_id: str
    issues: list[LintIssue] = field(default_factory=list)
    scanned_pages: int = 0


def lint_wiki(paths: WikiPaths, project_id: str = "default") -> LintReport:
    """Run all 5 lint checks against the wiki at ``paths``.

    Scans wiki_sources / wiki_entities / wiki_concepts / wiki_synthesis (skips
    stubs). Returns a LintReport with the collected issues and the page count.
    """
    ensure_knowledge_base(paths.root)

    issues: list[LintIssue] = []
    body_hashes: dict[str, list[str]] = {}
    pages_seen: set[str] = set()
    files_scanned = 0

    for sub in (
        paths.wiki_sources,
        paths.wiki_entities,
        paths.wiki_concepts,
        paths.wiki_synthesis,
    ):
        if not sub.exists():
            continue
        for md_file in sub.glob("*.md"):
            files_scanned += 1
            page = read_page(Path(md_file))
            pages_seen.add(page.id)

            if not page.id or not page.id.strip():
                issues.append(
                    LintIssue(
                        code="LINT-MISSING-ID",
                        severity=LintSeverity.WARNING,
                        message=f"Page missing id field: {md_file.name}",
                        page_id=md_file.stem,
                    )
                )

            if not page.title.strip():
                issues.append(
                    LintIssue(
                        code="LINT-MISSING-TITLE",
                        severity=LintSeverity.WARNING,
                        message=f"Page missing title: {page.id or md_file.stem}",
                        page_id=page.id or md_file.stem,
                    )
                )

            if not page.body.strip():
                issues.append(
                    LintIssue(
                        code="LINT-EMPTY-BODY",
                        severity=LintSeverity.INFO,
                        message=f"Page has empty body: {page.id}",
                        page_id=page.id,
                    )
                )

            content_hash = hashlib.md5(page.body.encode("utf-8")).hexdigest()
            body_hashes.setdefault(content_hash, []).append(page.id)

    # Orphans — pages on disk that are not listed in wiki/index.md
    indexed = {entry[0] for entry in read_index(paths)}
    for slug in pages_seen:
        if slug not in indexed:
            issues.append(
                LintIssue(
                    code="LINT-ORPHAN",
                    severity=LintSeverity.WARNING,
                    message=f"Page not in index: {slug}",
                    page_id=slug,
                )
            )

    # Duplicates — multiple pages sharing the same body md5
    for content_hash, slugs in body_hashes.items():
        if len(slugs) > 1:
            issues.append(
                LintIssue(
                    code="LINT-DUPLICATE",
                    severity=LintSeverity.WARNING,
                    message=f"Duplicate content: {', '.join(slugs)}",
                    page_id=slugs[0],
                )
            )

    return LintReport(
        project_id=project_id,
        issues=issues,
        scanned_pages=files_scanned,
    )