"""Batch metrics — M1/M2/M4/M6/M7 computed over a page set (spec §6).

Single measurement core shared by:
- Phase 0.1 baseline script (``scripts/audit_wiki_baseline.py``)
- Phase 1.8 batch-gate API (per-batch page-set mode)
- Phase 5 final acceptance (diff vs baseline)

Design notes (spec §6 / plan 0.1):
- M1 "未登记断链率": wikilink/relation target resolution against
  ``磁盘页 ∪ SlugAliasRegistry ∪ 索引``. Gap-registered links are NOT
  counted as broken here (F2); the caller subtracts the gap set.
- M2 "深引用率": share of raw .md files referenced by ≥1 NON-source page,
  excluding a raw's own self-produced pages (a raw R generates an
  entity/concept page whose ``sources`` lists only R — counting it would
  make M2 ≈ 100% by construction). A page counts as a deep reference only
  when it carries ≥2 sources or is a synthesis page.
- M6: synthesis page count (directory census).
- M7: source-page full-text pollution (`_FULLTEXT_SECTION_RE` hits).
- M4: helper counting MISSING-SECTION / placeholder issues from a lint
  report (the lint rules themselves live in ``features.lint``).

All metrics are deterministic, zero-LLM.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from ..core.paths import WikiPaths
from ..features.lint import _FULLTEXT_SECTION_RE, LintReport

# Heading of a full-text / transcript section that marks a source page as
# carrying verbatim raw content (shared with lint).
_PLACEHOLDER_SUBSTRINGS = (
    "（系统占位",
    "待补充",
    "见下游概念页",
    "来源未提供具体例子",
)

# YAML list field extractor — pulls the item lines under `key:`.
_LIST_ITEM_RE = re.compile(r"(?m)^\s*-\s*(.+)$")
# Key line of a YAML list field.
_LIST_KEY_RE = re.compile(r"(?m)^([a-z_]+):\s*$")
# Key line with inline value (scalar or inline list).
_SCALAR_KEY_RE = re.compile(r"(?m)^([a-z_]+):\s*(\S.*)$")
# Frontmatter delimiters.
_FM_SPLIT = "---"
# Wikilink in body.
_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


@dataclass
class PageSnapshot:
    """Owned, plain-data view of one wiki page (no live runtime objects)."""

    id: str
    path: Path
    page_type: str  # source | entity | concept | synthesis
    sources: list[str] = field(default_factory=list)  # normalized raw paths
    relations: list[dict] = field(default_factory=list)  # {target, type, ...}
    body: str = ""
    raw_frontmatter: str = ""


# ---------------------------------------------------------------------------
# Page reading
# ---------------------------------------------------------------------------

def _parse_frontmatter(text: str) -> tuple[str, str, dict[str, str]]:
    """Return (frontmatter_text, body_text, scalar_fields)."""
    parts = text.split(_FM_SPLIT, 2)
    if len(parts) >= 3:
        fm, body = parts[1], parts[2]
    else:
        fm, body = "", text
    fields: dict[str, str] = {}
    for m in _SCALAR_KEY_RE.finditer(fm):
        fields[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return fm, body, fields


def _list_field(fm: str, key: str) -> list[str]:
    """Extract item lines under a specific YAML list key from frontmatter.

    Matches the exact ``key:`` line (not the first list key, which could be
    ``sources`` when querying ``relations``). Continuation lines of an item
    (indented ``type:`` / ``weight:``) are skipped; a following top-level
    key ends the list.
    """
    m = re.search(rf"(?m)^{re.escape(key)}:\s*$", fm)
    if not m:
        return []
    seg = fm[m.end():]
    items: list[str] = []
    for line in seg.splitlines():
        if not line.strip():
            continue
        lm = _LIST_ITEM_RE.match(line)
        if lm:
            items.append(lm.group(1).strip().strip('"').strip("'"))
            continue
        if _LIST_KEY_RE.match(line) or _SCALAR_KEY_RE.match(line):
            break
    return items


def read_page_snapshots(files: Iterable[Path]) -> list[PageSnapshot]:
    """Read plain snapshots for a page-set (used by baseline + batch gate)."""
    out: list[PageSnapshot] = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        fm, body, fields = _parse_frontmatter(text)
        relations: list[dict] = []
        for line in _list_field(fm, "relations"):
            # Each item is itself a mapping; extract target/type when present.
            rel: dict[str, str] = {}
            for km in re.finditer(r"(?m)([a-z_]+):\s*(\S.*)$", line):
                rel[km.group(1)] = km.group(2).strip().strip('"').strip("'")
            if rel:
                relations.append(rel)
        out.append(
            PageSnapshot(
                id=fields.get("id", f.stem),
                path=f,
                page_type=fields.get("type", "concept"),
                sources=_list_field(fm, "sources"),
                relations=relations,
                body=body,
                raw_frontmatter=fm,
            )
        )
    return out


def collect_wikilinks(snapshot: PageSnapshot) -> list[str]:
    """All link targets of a page: body ``[[...]]`` plus relation targets."""
    targets = [m.group(1).strip() for m in _WIKILINK_RE.finditer(snapshot.body)]
    targets += [r.get("target", "") for r in snapshot.relations if r.get("target")]
    return [t for t in targets if t]


def page_ids(snapshots: Iterable[PageSnapshot]) -> set[str]:
    return {s.id for s in snapshots}


# ---------------------------------------------------------------------------
# M1 — unregistered broken-link rate
# ---------------------------------------------------------------------------

@dataclass
class BrokenLinksReport:
    total_links: int = 0
    broken_links: int = 0
    broken_slugs: list[str] = field(default_factory=list)

    @property
    def rate(self) -> float:
        if not self.total_links:
            return 0.0
        return self.broken_links / self.total_links


def metric_broken_links(
    snapshots: Iterable[PageSnapshot],
    known_slugs: set[str],
    alias_canonical: Callable[[str], str | None] | None = None,
    known_norm: set[str] | None = None,
) -> BrokenLinksReport:
    """M1: links whose target ∉ known_slugs ∪ (alias-resolvable).

    ``known_slugs`` should be 磁盘页 id 集合 ∪ 索引 entries. Gap-registered
    slugs are subtracted by the caller (F2 semantics).

    ``known_norm`` (Phase 3 实测修复): pre-normalised known-slug set via
    ``normalize_reconcile_slug`` so link-target variants (e.g. the
    double-hyphen ``老作者补贴体系--华夏天空`` vs the on-disk single-hyphen
    ``老作者补贴体系-华夏天空``) resolve instead of being counted as broken.
    When given, a target is resolvable if its normalised form is in
    ``known_norm``.
    """
    from .slug_utils import normalize_reconcile_slug

    report = BrokenLinksReport()
    seen: set[str] = set()
    for snap in snapshots:
        for target in collect_wikilinks(snap):
            report.total_links += 1
            if target in seen:
                continue
            seen.add(target)
            if target in known_slugs:
                continue
            if known_norm and normalize_reconcile_slug(target) in known_norm:
                continue
            if alias_canonical and alias_canonical(target):
                continue
            report.broken_links += 1
            report.broken_slugs.append(target)
    return report


# ---------------------------------------------------------------------------
# M2 — deep reference rate
# ---------------------------------------------------------------------------

def metric_deep_reference_rate(
    snapshots: Iterable[PageSnapshot],
    raw_md_files: Iterable[Path],
    project_root: Path | None = None,
) -> tuple[float, int, int]:
    """M2: share of raw .md files deeply referenced by wiki pages.

    A raw R is deeply referenced when ANY non-source page
    - lists R among ≥2 ``sources`` (multi-source page), OR
    - is a synthesis page listing R, OR
    - has a body wikilink pointing at R's source page (Phase 0.2 revised
      definition — the concept page's 参考来源 slot counts as real use).

    A concept/entity page whose ``sources`` lists exactly one raw is the
    product of that raw alone and does NOT constitute a deep reference
    (spec §6, plan 0.1/0.2).

    Returns ``(rate, referenced_raw_count, total_raw_count)``.
    """
    raw_abs: set[str] = {str(p).replace("\\", "/") for p in raw_md_files}
    # Relative forms (raw/sources/a.md) when project_root is known, because
    # frontmatter `sources` stores relative paths on this platform.
    rel_forms: set[str] = set()
    if project_root is not None:
        root_norm = str(project_root).replace("\\", "/").rstrip("/") + "/"
        for p in raw_md_files:
            absn = str(p).replace("\\", "/")
            if absn.startswith(root_norm):
                rel_forms.add(absn[len(root_norm):])

    def raw_hit(src: str) -> str | None:
        """Return a canonical raw path matching a frontmatter source entry."""
        norm = src.replace("\\", "/").lstrip("./")
        if norm in raw_abs:
            return norm
        if norm in rel_forms:
            return norm
        for cand in raw_abs:
            if cand.endswith(norm) or norm.endswith(cand):
                return cand
        return None

    # source-page id → raw paths (for the wikilink→source-page rule)
    source_raws: dict[str, set[str]] = {}
    all_snaps = list(snapshots)
    for snap in all_snaps:
        if snap.page_type != "source":
            continue
        for src in snap.sources:
            hit = raw_hit(src)
            if hit:
                source_raws.setdefault(snap.id, set()).add(hit)

    referenced: set[str] = set()
    for snap in all_snaps:
        if snap.page_type == "source":
            continue  # source pages do not count (F7)
        # (1) multi-source / synthesis sources
        if snap.sources:
            is_deep = snap.page_type == "synthesis" or len(snap.sources) >= 2
            if is_deep:
                for src in snap.sources:
                    hit = raw_hit(src)
                    if hit:
                        referenced.add(hit)
        # (2) wikilink → source page (Phase 0.2 revised definition)
        for target in collect_wikilinks(snap):
            if target in source_raws:
                referenced.update(source_raws[target])

    total = len(raw_abs)
    if total == 0:
        return 0.0, 0, 0
    return len(referenced) / total, len(referenced), total


# ---------------------------------------------------------------------------
# M4 — required-slot / placeholder compliance (helper over a lint report)
# ---------------------------------------------------------------------------

def metric_slot_compliance(report: LintReport) -> tuple[int, int, int]:
    """M4 helper: (missing_section_count, placeholder_count, other_error_count).

    Counts ERROR/WARNING issues from a lint report produced by
    ``features.lint.lint_wiki`` (the rules themselves live there; this
    helper only interprets the report for the metric).
    """
    missing = 0
    placeholder = 0
    other = 0
    for issue in report.issues:
        code = issue.code
        if code == "LINT-MISSING-SECTION":
            missing += 1
        elif code == "LINT-PLACEHOLDER":
            placeholder += 1
        else:
            other += 1
    return missing, placeholder, other


def body_has_placeholder(body: str) -> bool:
    """True when the rendered body contains a placeholder substring.

    Used by the future LINT-PLACEHOLDER rule and by the baseline scan.
    """
    return any(p in body for p in _PLACEHOLDER_SUBSTRINGS)


# ---------------------------------------------------------------------------
# M6 / M7 — synthesis census / source full-text pollution
# ---------------------------------------------------------------------------

def metric_synthesis_count(paths: WikiPaths) -> int:
    """M6: number of pages under wiki/synthesis/."""
    d = paths.wiki_synthesis
    if not d.exists():
        return 0
    return sum(1 for p in d.glob("*.md") if p.is_file())


def metric_source_fulltext_pollution(snapshots: Iterable[PageSnapshot]) -> int:
    """M7: count of source pages carrying a full-text section heading."""
    n = 0
    for snap in snapshots:
        if snap.page_type != "source":
            continue
        if _FULLTEXT_SECTION_RE.search(snap.body):
            n += 1
    return n


# ---------------------------------------------------------------------------
# Convenience: one-shot census over a wiki root (baseline / batch use)
# ---------------------------------------------------------------------------

def census_wiki(paths: WikiPaths) -> list[PageSnapshot]:
    """Read all pages under the four typed directories (skips _stubs)."""
    files: list[Path] = []
    for d in (paths.wiki_sources, paths.wiki_entities, paths.wiki_concepts, paths.wiki_synthesis):
        if d.exists():
            files.extend(sorted(d.glob("*.md")))
    return read_page_snapshots(files)
