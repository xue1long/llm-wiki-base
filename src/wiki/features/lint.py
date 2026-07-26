"""Wiki lint (A4) — runs 6 non-LLM checks across all wiki pages.

Detects: LINT-MISSING-ID, LINT-MISSING-TITLE, LINT-EMPTY-BODY,
LINT-MISSING-SECTION, LINT-ORPHAN, LINT-DUPLICATE.

LINT-MISSING-SECTION (Plan 27 / wiki v2.3 schema) is **version-gated**:
only pages whose leading HTML comment declares
``<!-- wiki-template-version: >= 2.0.0 -->` are checked. v1 pages are
exempt so existing wikis aren't noisy until they get re-ingested under
v2.3.

See LintSeverity for severities and LintIssue / LintReport for the
report shape. Public entry point is ``lint_wiki``.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from ..storage.ensure import ensure_knowledge_base
from .indexer import read_index
from ..storage.page_writer import read_page
from ..core.paths import WikiPaths
from ..templates import list_resolved, required_slot_names


# Leading HTML comment that declares which template version was used to
# render the page. Captured as group(1). Multiline-safe.
_TEMPLATE_VERSION_RE = re.compile(
    r"^<!--\s*wiki-template-version:\s*([0-9]+(?:\.[0-9]+){0,2})\s*-->",
    re.MULTILINE,
)
# Heading lines emitted in the rendered body so we can extract exactly
# which sections are present vs missing per the active template.
_BODY_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


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


def _parse_version(version_str: str) -> tuple[int, ...]:
    """Parse a dotted version string into a comparable tuple.

    Missing components default to 0; e.g. ``"2"`` → ``(2, 0, 0)``,
    ``"2.1"`` → ``(2, 1, 0)``.
    """
    parts: list[int] = []
    for piece in version_str.split("."):
        try:
            parts.append(int(piece))
        except ValueError:
            return ()
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def lint_wiki(paths: WikiPaths, project_id: str = "default") -> LintReport:
    """Run all 6 lint checks against the wiki at ``paths``.

    Scans wiki_sources / wiki_entities / wiki_concepts / wiki_synthesis (skips
    stubs). Returns a LintReport with the collected issues and the page count.
    """
    ensure_knowledge_base(paths.root)

    issues: list[LintIssue] = []
    body_hashes: dict[str, list[str]] = {}
    pages_seen: set[str] = set()
    files_scanned = 0

    # Resolve templates once per lint run (so missing-template pages fail
    # with a clear message rather than throwing mid-loop).
    try:
        resolved_templates = {t.type: t for t in list_resolved(paths.root)}
    except Exception:
        resolved_templates = {}

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

            # LINT-MISSING-SECTION: v2+ template pages must include every
            # required heading. The parser strips the leading comment from
            # page.body, so we re-read the raw file to read it.
            try:
                raw = md_file.read_text(encoding="utf-8")
            except OSError:
                raw = ""
            vm = _TEMPLATE_VERSION_RE.search(raw)
            if vm and _parse_version(vm.group(1)) >= (2, 0, 0):
                template = resolved_templates.get(page.type)
                if template is not None:
                    try:
                        required = required_slot_names(template)
                    except Exception:
                        required = []
                    if required:
                        # Each required slot maps to a `## Heading` whose
                        # label is the slot name as written in the bundled
                        # template. We compare by literal heading text.
                        template_headings = {
                            _heading_label(name) for name in required
                        }
                        body_headings = set(_BODY_HEADING_RE.findall(page.body))
                        missing = sorted(
                            h for h in template_headings if h not in body_headings
                        )
                        if missing:
                            issues.append(
                                LintIssue(
                                    code="LINT-MISSING-SECTION",
                                    severity=LintSeverity.WARNING,
                                    message=(
                                        "Page is missing required sections "
                                        f"(template version >= 2.0.0): {missing}"
                                    ),
                                    page_id=page.id,
                                    suggestion=(
                                        "Re-ingest the source so the page is "
                                        "regenerated against the v2.3 schema, "
                                        "or add the missing sections manually."
                                    ),
                                )
                            )

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


def _heading_label(slot_name: str) -> str:
    """Map a slot name to the template heading it's rendered under.

    The bundled templates use the slot name as the heading label (e.g.
    slot ``"definition"`` → heading "定义"; slot ``"source_meta"`` →
    heading "来源元数据"). This mapping is hardcoded against the bundled
    defaults and will need extension if a project or user template
    diverges.
    """
    return _SLOT_TO_HEADING.get(slot_name, slot_name)


# Mapping from canonical bundled slot names to the literal heading used
# in their ## sections. Single source of truth — keep in lock-step with
# src/wiki/templates/bundled/*.md.
_SLOT_TO_HEADING = {
    # source.md
    "source_meta": "来源元数据",
    "summary": "摘要",
    "key_points": "关键观点",
    "extracted_concepts": "抽取的概念",
    # entity.md
    "basic_info": "基本信息",
    "related": "相关引用",
    # concept.md
    "definition": "定义",
    "characteristics": "主要特点",
    "examples": "例子",
    "related_concepts": "相关概念",
    "references": "参考来源",
    # synthesis.md
    "comparison_dimensions": "对比维度",
    "overview": "综述",
    "involved_concepts": "涉及的概念",
    "comparison": "对比表",
    "conclusion": "结论",
}