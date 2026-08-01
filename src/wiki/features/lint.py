"""Wiki lint (A4) — runs 9 non-LLM checks across all wiki pages.

Detects: LINT-MISSING-ID, LINT-MISSING-TITLE, LINT-EMPTY-BODY,
LINT-MISSING-SECTION, LINT-ORPHAN, LINT-DUPLICATE, LINT-RAW-PASTE,
LINT-MISSING-SOURCES, LINT-UGC-CRED.

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
from ..core.types import PageType
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
# Fenced code block delimiters. Lines between two such markers are exempt
# from LINT-RAW-PASTE (they are intentionally verbatim).
_FENCE_RE = re.compile(r"^\s*(?:```|~~~)")
# List-item markers: "- ", "* " (unordered) or "1. " / "1) " (ordered),
# with optional leading indentation. Also catches "+ " / "• " variants.
_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+•]\s|\d+[.)]\s)")

# A plain-text run longer than this many characters is treated as a raw
# paste rather than curated wiki prose.
_RAW_PASTE_THRESHOLD = 300

# NDG Phase 2 — dual threshold for RAW-PASTE (source vs non-source).
# Source pages carry distilled summaries, not full text; a source page
# body that balloons past T_source is likely raw paste.  Non-source pages
# use a tighter threshold.  These are fallback defaults; the authoritative
# values live in ``.index/quality_settings.json`` under the ``raw_paste``
# key (written by Phase 0 calibration).
_DEFAULT_T_SOURCE = 2000   # chars — generous; source-page summaries are ~300-800
_DEFAULT_T_NON = 300       # chars — same as the old single threshold

# NDG Phase 2 — full-text section heading detector.
# A source page that still has a "full text" / "transcript" / "original"
# section is carrying verbatim raw content and must be flagged regardless
# of run length.
_FULLTEXT_SECTION_RE = re.compile(
    r"^#{1,6}\s*(正文内容|转录内容|原文|全文|完整文本)\s*$",
    re.MULTILINE,
)


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


# ---------------------------------------------------------------------------
# Page-level predicates (single source of truth)
# ---------------------------------------------------------------------------
# The NDG gate (P1/P3/P4) and ``cli lint`` share these decision predicates so
# the two never diverge.  Each returns a plain answer about one page; the
# callers wrap it in their own issue type / severity.

_READABILITY_PLACEHOLDERS = {"(empty)", "(无内容)", "(占位)", "(placeholder)"}


def _readability_violation(page) -> str | None:
    """Return the first readability violation, or ``None`` for a clean page.

    Order of checks (first match wins, mirroring the gate's P1):
    ``empty_id`` → ``empty_title`` → ``empty_body`` → ``placeholder``.
    """
    if not page.id or not page.id.strip():
        return "empty_id"
    if not page.title or not page.title.strip():
        return "empty_title"
    if not page.body or not page.body.strip():
        return "empty_body"
    if page.body.strip() in _READABILITY_PLACEHOLDERS:
        return "placeholder"
    return None


def _missing_sources(page) -> bool:
    """True when the page lists no sources and no derivation relation."""
    rel_types = {
        r.type if isinstance(r.type, str) else r.type.value
        for r in (page.relations or [])
    }
    return not page.sources and not (
        rel_types & {"derived_from", "supported_by"}
    )


def _missing_ugc_cred(page) -> bool:
    """True when the page is UGC-tagged but lacks the credibility tag."""
    return "素材/ugc" in page.tags and "可信度/ugc" not in page.tags


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


def _long_raw_text_run(body: str) -> int:
    """Length of the longest run of "plain prose" lines in ``body``.

    A plain-prose line is non-empty and is NOT a blockquote, NOT a list
    item, and NOT inside a fenced code block. Blank lines, blockquotes,
    list items, and fence boundaries all reset the current run. The
    returned value is the character length of the longest qualifying run.
    """
    longest = 0
    current = 0
    in_fence = False
    for line in body.split("\n"):
        stripped = line.strip()
        if _FENCE_RE.match(stripped):
            in_fence = not in_fence
            current = 0
            continue
        if in_fence or not stripped:
            current = 0
            continue
        if stripped.startswith(">") or _LIST_ITEM_RE.match(stripped):
            current = 0
            continue
        current += len(stripped)
        if current > longest:
            longest = current
    return longest


def _has_fulltext_section(body: str) -> bool:
    """True if *body* contains a full-text / transcript section heading.

    Only matches headings that appear **outside** fenced code blocks
    (same fence-awareness as ``_long_raw_text_run``) so that a
    documentation page that *mentions* ``## 正文内容`` inside a code
    sample is not falsely flagged.
    """
    in_fence = False
    for line in body.split("\n"):
        stripped = line.strip()
        if _FENCE_RE.match(stripped):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if _FULLTEXT_SECTION_RE.match(stripped):
            return True
    return False


def _load_raw_paste_thresholds(paths: WikiPaths) -> tuple[int, int]:
    """Return ``(T_source, T_non)`` from the project quality-settings file.

    Reads ``.index/quality_settings.json``, key ``raw_paste`` with
    sub-keys ``source_threshold`` and ``non_source_threshold``.  Falls
    back to :data:`_DEFAULT_T_SOURCE` / :data:`_DEFAULT_T_NON` when the
    file or keys are absent, corrupt, or contain invalid values.
    """
    import json as _json

    settings_path = paths.index / "quality_settings.json"
    try:
        data = _json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, _json.JSONDecodeError):
        return _DEFAULT_T_SOURCE, _DEFAULT_T_NON

    rp = data.get("raw_paste", {}) if isinstance(data, dict) else {}
    if not isinstance(rp, dict):
        return _DEFAULT_T_SOURCE, _DEFAULT_T_NON

    try:
        ts = int(rp.get("source_threshold", _DEFAULT_T_SOURCE))
    except (TypeError, ValueError):
        ts = _DEFAULT_T_SOURCE
    try:
        tn = int(rp.get("non_source_threshold", _DEFAULT_T_NON))
    except (TypeError, ValueError):
        tn = _DEFAULT_T_NON

    return ts, tn


def lint_wiki(paths: WikiPaths, project_id: str = "default") -> LintReport:
    """Run all 9 lint checks against the wiki at ``paths``.

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
        logger.warning("Failed to resolve templates for lint; using empty set", exc_info=True)
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

            _read_violation = _readability_violation(page)
            if _read_violation == "empty_id":
                issues.append(
                    LintIssue(
                        code="LINT-MISSING-ID",
                        severity=LintSeverity.WARNING,
                        message=f"Page missing id field: {md_file.name}",
                        page_id=md_file.stem,
                    )
                )
            elif _read_violation == "empty_title":
                issues.append(
                    LintIssue(
                        code="LINT-MISSING-TITLE",
                        severity=LintSeverity.WARNING,
                        message=f"Page missing title: {page.id or md_file.stem}",
                        page_id=page.id or md_file.stem,
                    )
                )
            elif _read_violation == "empty_body":
                issues.append(
                    LintIssue(
                        code="LINT-EMPTY-BODY",
                        severity=LintSeverity.INFO,
                        message=f"Page has empty body: {page.id}",
                        page_id=page.id,
                    )
                )

            # Skip duplicate detection for empty-body pages
            if page.body.strip():
                content_hash = hashlib.md5(page.body.encode("utf-8")).hexdigest()
                body_hashes.setdefault(content_hash, []).append(page.id)

            # LINT-RAW-PASTE (NDG Phase 2): source pages are NO LONGER
            # exempt.  The source template now produces distilled summaries,
            # not full text.  Two independent checks:
            #
            #   Source pages: fulltext-section heading  →  flag
            #                 raw-run > T_source        →  flag
            #   Non-source:   raw-run > T_non           →  flag
            #
            # Thresholds are loaded from .index/quality_settings.json so
            # Phase 0 calibration can tune them per-project; fall back to
            # internal constants when the file is absent.
            T_source, T_non = _load_raw_paste_thresholds(paths)
            raw_run = _long_raw_text_run(page.body)

            if page.type == PageType.SOURCE:
                # Check 1: fulltext-section heading (unconditionally flag).
                if _has_fulltext_section(page.body):
                    issues.append(
                        LintIssue(
                            code="LINT-RAW-PASTE",
                            severity=LintSeverity.WARNING,
                            message=(
                                "Source page body contains a full-text / "
                                "transcript section heading (e.g. 正文内容, "
                                "转录内容, 原文, 全文, 完整文本) — raw text "
                                "should live in raw/sources/, not the wiki."
                            ),
                            page_id=page.id,
                            suggestion=(
                                "Re-ingest the source so the Generator produces "
                                "a distilled summary instead of echoing the "
                                "full document."
                            ),
                        )
                    )
                # Check 2: long raw run past the source threshold.
                elif raw_run > T_source:
                    issues.append(
                        LintIssue(
                            code="LINT-RAW-PASTE",
                            severity=LintSeverity.WARNING,
                            message=(
                                f"Source page body contains a {raw_run}-char "
                                f"run of unstructured plain text (threshold "
                                f"{T_source}) — possible raw paste instead of "
                                f"distilled summary."
                            ),
                            page_id=page.id,
                            suggestion=(
                                "Re-ingest with the updated source template "
                                "so the Generator writes a short summary, "
                                "not the full document body."
                            ),
                        )
                    )
            else:
                if raw_run > T_non:
                    issues.append(
                        LintIssue(
                            code="LINT-RAW-PASTE",
                            severity=LintSeverity.WARNING,
                            message=(
                                f"Page body contains a {raw_run}-char run of "
                                "unstructured plain text (possible raw paste)"
                            ),
                            page_id=page.id,
                            suggestion=(
                                "Split the prose into sections, list items, or "
                                "blockquotes, or move the verbatim text into the "
                                "page's source file."
                            ),
                        )
                    )

            # LINT-MISSING-SOURCES: a page should either list its raw source
            # file(s) or declare a derivation relation (derived_from /
            # supported_by). A synthesis page that enumerates its sources is
            # fine; only a page with neither signal is flagged.
            if _missing_sources(page):
                issues.append(
                    LintIssue(
                        code="LINT-MISSING-SOURCES",
                        severity=LintSeverity.WARNING,
                        message=(
                            f"Page has no sources and no derived/supported "
                            f"relation: {page.id}"
                        ),
                        page_id=page.id,
                        suggestion=(
                            "Add the raw source path(s) to the page's sources, "
                            "or add a derived_from / supported_by relation."
                        ),
                    )
                )

            # LINT-UGC-CRED: UGC-sourced material (素材/ugc) must also carry a
            # credibility tag (可信度/ugc) so readers know how it was verified.
            if _missing_ugc_cred(page):
                issues.append(
                    LintIssue(
                        code="LINT-UGC-CRED",
                        severity=LintSeverity.WARNING,
                        message=(
                            f"Page tagged 素材/ugc but missing the 可信度/ugc "
                            f"credibility tag: {page.id}"
                        ),
                        page_id=page.id,
                        suggestion=(
                            "Add the 可信度/ugc tag to record how the UGC "
                            "material was verified."
                        ),
                    )
                )

            # LINT-MISSING-SECTION: v2+ template pages must include every
            # required heading. The parser strips the leading comment from
            # page.body, so we re-read the raw file to read it.
            try:
                raw = md_file.read_text(encoding="utf-8")
            except OSError:
                raw = ""
            vm = _TEMPLATE_VERSION_RE.search(raw)
            if vm and _parse_version(vm.group(1)) >= (2, 0, 0):
                if page.processing_depth == "stub":
                    continue
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
                            _heading_label(name, page.type) for name in required
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


def _heading_label(slot_name: str, page_type: str = "") -> str:
    """Map a slot name to the template heading it's rendered under.

    The bundled templates use the slot name as the heading label (e.g.
    slot ``"definition"`` → heading "定义"; slot ``"source_meta"`` →
    heading "来源元数据"). This mapping is hardcoded against the bundled
    defaults and will need extension if a project or user template
    diverges.
    """
    if page_type == "entity" and slot_name == "summary":
        return "简介"
    return _SLOT_TO_HEADING.get(slot_name, slot_name)


# Mapping from canonical bundled slot names to the literal heading used
# in their ## sections. Single source of truth — keep in lock-step with
# src/wiki/templates/bundled/*.md.
_SLOT_TO_HEADING = {
    # source.md
    "source_meta": "来源元数据",
    "summary": "摘要",
    "main_content": "正文内容",
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