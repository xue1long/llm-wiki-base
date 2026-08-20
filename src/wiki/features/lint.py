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
import logging
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from ..storage.ensure import ensure_knowledge_base
from .indexer import read_index

logger = logging.getLogger(__name__)
from ..storage.page_writer import read_page
from ..core.types import VALID_PROCESSING_DEPTHS, VALID_WORKFLOW_STATES
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
# T_source tightened 2000 → 800 (v3.0.0 source template drops main_content;
# summaries are 300–800 chars — F5×H7 follow-up, Phase 3 calibrates).
_DEFAULT_T_SOURCE = 800    # chars — v3.0.0 source summaries ~300-800
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

# Placeholder substrings that must never appear in a rendered body
# (substring match, unlike _READABILITY_PLACEHOLDERS' whole-body equality).
_PLACEHOLDER_SUBSTRINGS = (
    "（系统占位",
    "待补充",
    "见下游概念页",
    "来源未提供具体例子",
)

# 17 built-in relation types (src/pipeline/generator.py) — anything else
# (unless x-*) is illegal.
_BUILTIN_RELATIONS = frozenset({
    "is_part_of", "contains", "references", "referenced_by", "causes",
    "caused_by", "contradicts", "supports", "supported_by", "supersedes",
    "superseded_by", "depends_on", "required_by", "analogous_to",
    "opposite_of", "derived_from", "derives",
})

# Heading under which the v3.0.0 synthesis template lists viewpoint rows.
_VIEWPOINTS_HEADING = "各方观点"


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


# UGC carrier detection (R3-1 / D5).  A raw file is a "UGC carrier" when its
# first ~4000 characters reference a known UGC platform (feishu.cn,
# mp.weixin.qq.com, 飞书云文档, 公众号, 论坛, 知乎, 豆瓣, 简书, QQ群).
# Shared by the phase4 auto-tag step and the NDG gate's P4b check so the two
# never diverge.
_UGC_CARRIER_RE = re.compile(
    r"feishu\.cn|mp\.weixin\.qq\.com|飞书云文档|公众号|论坛|知乎|豆瓣|简书|QQ群",
    re.IGNORECASE,
)


def _is_ugc_carrier(header: str) -> bool:
    """True when *header* (a raw file's first ~4000 chars) is a UGC carrier.

    Deterministic, zero LLM cost.  Case- and whitespace-tolerant: whitespace
    is compacted out of the input before the regex runs, so ``" 飞 书 云 文 档 "``
    and ``"FEISHU.CN"`` both hit.
    """
    if not header:
        return False
    return _UGC_CARRIER_RE.search("".join(header.split())) is not None


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


def _count_viewpoint_links(body: str) -> int:
    """Count [[wikilinks]] inside the synthesis 各方观点 section.

    The section runs from its heading to the next ``## `` heading. Fenced
    code blocks are skipped. This is the F1-correct gate: it counts
    resolvable link targets (existence check is done by the caller/对账),
    independent of the frontmatter ``sources`` count.
    """
    lines = body.split("\n")
    in_section = False
    in_fence = False
    count = 0
    for line in lines:
        stripped = line.strip()
        if _FENCE_RE.match(stripped):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if stripped.startswith("## "):
            if stripped.lstrip("#").strip() == _VIEWPOINTS_HEADING:
                in_section = True
                continue
            if in_section:
                break
        if in_section:
            count += len(re.findall(r"\[\[([^\]]+)\]\]", line))
    return count


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


def lint_wiki(
    paths: WikiPaths,
    project_id: str = "default",
    page_ids: set[str] | None = None,
) -> LintReport:
    """Run all lint checks against the wiki at ``paths``.

    Scans wiki_sources / wiki_entities / wiki_concepts / wiki_synthesis (skips
    stubs). When *page_ids* is given, only pages whose ``id`` is in the set
    are scanned — the batch-scope mode (plan 1.8) so the gate measures a
    batch instead of the whole library (whole-library orphans / legacy noise
    must not pollute batch verdicts). Returns a LintReport.
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
            page = read_page(Path(md_file))
            if page_ids is not None and page.id not in page_ids:
                continue
            files_scanned += 1
            pages_seen.add(page.id)

            # Read the raw file once for the template-version header (shared
            # by MISSING-SECTION and SYNTHESIS-GATE).
            try:
                raw = md_file.read_text(encoding="utf-8")
            except OSError:
                raw = ""
            vm = _TEMPLATE_VERSION_RE.search(raw)

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

            # Workflow state lint checks (P17 + P27)
            _ws = page.workflow_state or "draft"
            if _ws not in VALID_WORKFLOW_STATES:
                issues.append(
                    LintIssue(
                        code="LINT-INVALID-WORKFLOW-STATE",
                        severity=LintSeverity.ERROR,
                        message=f"Invalid workflow_state: {page.workflow_state!r}",
                        page_id=page.id,
                    )
                )
            if _ws == "verified" and page.verified_at <= 0:
                issues.append(
                    LintIssue(
                        code="LINT-INVALID-VERIFIED-AT",
                        severity=LintSeverity.WARNING,
                        message="workflow_state=verified but verified_at is not set",
                        page_id=page.id,
                    )
                )
            _pd = page.processing_depth or "concept"
            if _pd not in VALID_PROCESSING_DEPTHS:
                issues.append(
                    LintIssue(
                        code="LINT-INVALID-PROCESSING-DEPTH",
                        severity=LintSeverity.ERROR,
                        message=f"Invalid processing_depth: {page.processing_depth!r}",
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
                            severity=LintSeverity.ERROR,
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

            # LINT-PLACEHOLDER: no placeholder substring may appear in a body
            # (system placeholders / 待补充 / 见下游概念页 / 来源未提供具体例子).
            # Substring match — complements _READABILITY_PLACEHOLDERS (whole-body).
            if any(p in page.body for p in _PLACEHOLDER_SUBSTRINGS):
                issues.append(
                    LintIssue(
                        code="LINT-PLACEHOLDER",
                        severity=LintSeverity.ERROR,
                        message=(
                            f"Page body contains a placeholder substring: {page.id}"
                        ),
                        page_id=page.id,
                        suggestion=(
                            "Replace the placeholder with substantive content "
                            "or a truthful '无相关引用' statement."
                        ),
                    )
                )

            # LINT-ILLEGAL-RELATION: relations[].type must be one of the 17
            # built-ins or an x-* user type (M9 / plan 1.2-6).
            for rel in (page.relations or []):
                rtype = rel.type if isinstance(rel.type, str) else rel.type.value
                if rtype not in _BUILTIN_RELATIONS and not rtype.startswith("x-"):
                    issues.append(
                        LintIssue(
                            code="LINT-ILLEGAL-RELATION",
                            severity=LintSeverity.ERROR,
                            message=(
                                f"Illegal relation type {rtype!r} on page {page.id}"
                            ),
                            page_id=page.id,
                            suggestion=(
                                "Use one of the 17 built-in relation types or "
                                "register an x-<name> type."
                            ),
                        )
                    )

            # LINT-TAGS-ENUM: tag values must fall within the controlled
            # vocabulary defined in tag_namespace.TAG_VALUES.  Reuses the
            # existing validate_tag_values() so the enum is single-source.
            if page.tags:
                from ..features.tag_namespace import validate_tag_values
                invalid_tags = validate_tag_values(page.tags)
                if invalid_tags:
                    issues.append(
                        LintIssue(
                            code="LINT-TAGS-ENUM",
                            severity=LintSeverity.ERROR,
                            message=(
                                f"Page has tags outside controlled vocabulary: "
                                f"{invalid_tags} on page {page.id}"
                            ),
                            page_id=page.id,
                            suggestion=(
                                "Use tags from the controlled vocabulary "
                                "(see tag_namespace.TAG_VALUES)."
                            ),
                        )
                    )

            # LINT-SYNTHESIS-GATE: v3.0.0 synthesis pages must carry at least
            # 2 resolvable [[wikilinks]] inside the 各方观点 section (F1 — the
            # gate must not rely on frontmatter `sources` count, which is
            # always 1 for pipeline-generated pages).
            if _parse_version(vm.group(1)) >= (3, 0, 0) if vm else False:
                if page.type == PageType.SYNTHESIS:
                    viewpoints_links = _count_viewpoint_links(page.body)
                    if viewpoints_links < 2:
                        issues.append(
                            LintIssue(
                                code="LINT-SYNTHESIS-GATE",
                                severity=LintSeverity.ERROR,
                                message=(
                                    "Synthesis page has fewer than 2 wikilinks "
                                    f"in the {_VIEWPOINTS_HEADING} section: "
                                    f"{page.id}"
                                ),
                                page_id=page.id,
                                suggestion=(
                                    "Each viewpoint must cite a source page "
                                    "via [[wikilink]]."
                                ),
                            )
                        )

            # LINT-MISSING-SECTION: v2+ template pages must include every
            # required heading. The parser strips the leading comment from
            # page.body, so we re-read the raw file to read it (vm already
            # captured above).
            if vm and _parse_version(vm.group(1)) >= (2, 0, 0):
                if page.processing_depth == "stub":
                    continue
                template = resolved_templates.get(page.type)
                if template is not None:
                    page_ver = _parse_version(vm.group(1))
                    project_ver = _parse_version(template.version or "2.0.0")
                    # H3 版本门（Phase 3 实测修复）：存量 2.0.0 页在项目级
                    # v3.0.0 模板下仍按 **bundled 2.0.0** 模板的槽集检查，
                    # 不得被要求填 v3.0.0 新增槽（适用场景/反模式/证据强度）。
                    # 只有页声明版本 >= 项目解析模板版本才用项目模板槽集。
                    if page_ver < project_ver:
                        baseline = _bundled_template(page.type)
                        if baseline is None:
                            continue
                        try:
                            required = required_slot_names(baseline)
                        except Exception:
                            required = []
                        if not required:
                            continue
                        template_headings = {
                            _heading_label(n, page.type.value) for n in required
                        }
                    else:
                        try:
                            required = required_slot_names(template)
                        except Exception:
                            required = []
                        if not required:
                            continue
                        heading_map = _template_heading_map(template, page.type)
                        template_headings = {
                            heading_map.get(n, _heading_label(n, page.type))
                            for n in required
                        }
                    body_headings = set(_BODY_HEADING_RE.findall(page.body))
                    missing = sorted(
                        h for h in template_headings if h not in body_headings
                    )
                    if missing:
                        issues.append(
                            LintIssue(
                                code="LINT-MISSING-SECTION",
                                severity=LintSeverity.ERROR,
                                message=(
                                    "Page is missing required sections "
                                    f"(template version >= 2.0.0): {missing}"
                                ),
                                page_id=page.id,
                                suggestion=(
                                    "Re-ingest the source so the page is "
                                    "regenerated against the active template, "
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


def _bundled_template(page_type: PageType):
    """Resolve the bundled (default 2.0.0) template for a PageType.

    Phase 3 实测修复：lint 版本门对"页声明版本 < 项目模板版本"的存量页
    （如项目级 v3.0.0 下的 2.0.0 页）需以 bundled 模板的必填槽为检查基准，
    否则会被误要求填 v3.0.0 新增槽。resolve() 自身带 mtime-keyed LRU。
    """
    from ..templates import resolve as _resolve
    from ..templates.types import BUNDLED_DIR

    try:
        return _resolve(page_type, BUNDLED_DIR)
    except Exception:
        return None


def _template_heading_map(template, page_type: str) -> dict[str, str]:
    """slot-name → ## heading map derived from the resolved template AST.

    Preferred over the hardcoded ``_SLOT_TO_HEADING`` for pages whose
    declared template version matches the project-resolved template
    (H1): v3.0.0 synthesis reuses slot ``conclusion`` under the heading
    "待定与结论" while bundled 2.0.0 calls it "结论" — a single hardcoded
    map cannot express both.
    """
    from ..templates.parser import parse as _parse_tpl

    try:
        ast = _parse_tpl(template.body_markdown, expected_type=PageType(page_type))
    except Exception:
        return {}
    out: dict[str, str] = {}
    for section in ast.sections:
        for slot in section.slots:
            # Strip the `## ` prefix so the map matches _BODY_HEADING_RE
            # output ('定义', not '## 定义').
            out[slot.name] = section.heading.lstrip("#").strip()
    return out


# Mapping from canonical bundled slot names to the literal heading used
# in their ## sections. Single source of truth — keep in lock-step with
# src/wiki/templates/bundled/*.md AND project-level v3.0.0 templates.
_SLOT_TO_HEADING = {
    # source.md (bundled 2.0.0 + project v3.0.0)
    "source_meta": "来源元数据",
    "summary": "摘要",
    "main_content": "正文内容",
    "key_points": "关键观点",
    "extracted_concepts": "抽取的概念",
    # project v3.0.0 additions
    "transcription_quality": "转录质量",
    "credibility": "可信度声明",
    # entity.md
    "basic_info": "基本信息",
    "related": "相关引用",
    # project v3.0.0 additions
    "craft_value": "写作价值",
    # concept.md
    "definition": "定义",
    "characteristics": "主要特点",
    "examples": "例子",
    "related_concepts": "相关概念",
    "references": "参考来源",
    # project v3.0.0 additions
    "context": "适用场景",
    "anti_patterns": "反模式与常见错误",
    "evidence": "证据强度",
    # synthesis.md (bundled 2.0.0)
    "comparison_dimensions": "对比维度",
    "overview": "综述",
    "involved_concepts": "涉及的概念",
    "comparison": "对比表",
    "conclusion": "结论",
    # project v3.0.0 synthesis (分歧汇聚) — note: conclusion is reused
    "topic": "议题与分歧点",
    "viewpoints": "各方观点",
    "consensus": "共识",
    "evidence_comparison": "证据对比",
}
