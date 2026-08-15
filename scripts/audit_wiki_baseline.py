"""Phase 0 baseline audit — read-only stats for a ruflo-kb wiki.

Computes the spec §6 metrics (M1/M2/M6/M7 via ``src/wiki/features/metrics``)
plus the audit-baseline counts used by docs/guides/novel-wiki-ingest-spec.md
第 10 节: raw file count, wiki page count per type, coverage, grade-C pages,
placeholder-body pollution, per-dir page tallies, stub pages, legacy tag
prefix pages, illegal relation types.

Usage:
    env PYTHONIOENCODING=utf-8 python scripts/audit_wiki_baseline.py <wiki_root>
    python scripts/audit_wiki_baseline.py <wiki_root> --json .index/baseline.json

Output is ASCII-only on stdout (counts + ASCII labels) so it is robust to
Windows console codepages. All Chinese page ids are intentionally NOT
printed here; use grep/glob for UTF-8 detail.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── src import (script runs from repo root; PYTHONPATH=. in dev) ──────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.wiki.core.paths import WikiPaths  # noqa: E402
from src.wiki.features.metrics import (  # noqa: E402
    census_wiki,
    metric_broken_links,
    metric_deep_reference_rate,
    metric_source_fulltext_pollution,
    metric_synthesis_count,
    page_ids,
)

# Old English tag prefixes (deprecated since 2026-08-01 Chinese cut-over).
_LEGACY_TAG_PREFIXES = ("genre/", "func/", "char/", "event/", "mood/",
                        "entity/", "scene_phase/", "status/")
# 17 built-in relation types (generator.py) — anything else (non x-*) is illegal.
_BUILTIN_RELATIONS = {
    "is_part_of", "contains", "references", "referenced_by", "causes",
    "caused_by", "contradicts", "supports", "supported_by", "supersedes",
    "superseded_by", "depends_on", "required_by", "analogous_to",
    "opposite_of", "derived_from", "derives",
}


def read_frontmatter(path: Path) -> tuple[str, str, dict[str, str]]:
    """Return (frontmatter_text, body_text, fields)."""
    text = path.read_text(encoding="utf-8", errors="replace")
    parts = text.split("---", 2)
    if len(parts) >= 3:
        fm, body = parts[1], parts[2]
    else:
        fm, body = "", text
    fields: dict[str, str] = {}
    for m in re.finditer(r"(?m)^([a-z_]+):\s*(.*)$", fm):
        fields[m.group(1)] = m.group(2).strip()
    return fm, body, fields


def list_field_nonempty(fm: str, key: str) -> bool:
    """True if a YAML list field has at least one item."""
    m = re.search(rf"(?m)^\s*{key}:[ \t]*(.*)$", fm)
    if not m:
        return False
    rest = m.group(1).strip()
    if rest.startswith("["):
        return rest.strip("[]") != ""
    if rest:
        return True
    tail = fm[m.end():]
    return bool(re.match(r"\s*-\s*\S", tail))


def _normalize(raw: str) -> str:
    return raw.replace("\\", "/")


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: audit_wiki_baseline.py <wiki_root> [--json <path>]")
        sys.exit(2)
    root = Path(sys.argv[1])
    json_out: str | None = None
    if "--json" in sys.argv:
        i = sys.argv.index("--json")
        if i + 1 < len(sys.argv):
            json_out = sys.argv[i + 1]
    raw_root = root / "raw"
    wiki_root = root / "wiki"
    paths = WikiPaths(root)

    raw_files = [p for p in raw_root.rglob("*") if p.is_file()]
    raw_md = [p for p in raw_files if p.suffix.lower() == ".md"]

    dirs = {
        "sources": (wiki_root / "sources", "source"),
        "entities": (wiki_root / "entities", "entity"),
        "concepts": (wiki_root / "concepts", "concept"),
        "synthesis": (wiki_root / "synthesis", "synthesis"),
    }
    per_type = {ptype: 0 for _, ptype in dirs.values()}
    empty_sources = 0
    empty_relations = 0
    grade_c = 0
    placeholder = 0
    stub = 0
    legacy_tag_pages = 0
    illegal_relation_pages = 0
    illegal_relation_sites = 0
    md5_groups: dict[str, list[str]] = {}
    total = 0

    for name, (d, ptype) in dirs.items():
        if not d.exists():
            continue
        for f in sorted(d.glob("*.md")):
            total += 1
            per_type[ptype] += 1
            fm, body, fields = read_frontmatter(f)
            if not list_field_nonempty(fm, "sources"):
                empty_sources += 1
            if not list_field_nonempty(fm, "relations"):
                empty_relations += 1
            if fields.get("grade") == "C":
                grade_c += 1
            if fields.get("processing_depth") == "stub":
                stub += 1
            if "占位" in body or "系统占位" in body:
                placeholder += 1
            # Legacy English tag prefixes
            tags_seg = re.search(r"(?m)^tags:[ \t]*(.*)$", fm)
            if tags_seg:
                tail = fm[tags_seg.end():]
                tag_lines = re.findall(r"(?m)^\s*-\s*(.+)$", tail)
                if any(any(t.strip().startswith(p) for p in _LEGACY_TAG_PREFIXES)
                       for t in tag_lines):
                    legacy_tag_pages += 1
            # Illegal relation types (scan whole relations block, not just
            # `- ` item lines — `type:` lives on an indented continuation line)
            rel_seg = re.search(r"(?m)^relations:[ \t]*(.*)$", fm)
            if rel_seg:
                block_lines: list[str] = []
                for line in fm[rel_seg.end():].splitlines():
                    if re.match(r"(?m)^[a-z_]+:[ \t]*", line):
                        break
                    block_lines.append(line)
                block = "\n".join(block_lines)
                for tm in re.finditer(r"(?m)type:[ \t]*(\S+)", block):
                    rtype = tm.group(1).strip().strip('"').strip("'")
                    if rtype not in _BUILTIN_RELATIONS and not rtype.startswith("x-"):
                        illegal_relation_sites += 1
                        illegal_relation_pages += 1
            if body.strip():
                h = hashlib.md5(body.encode("utf-8")).hexdigest()
                md5_groups.setdefault(h, []).append(str(f))

    dup_groups = {h: v for h, v in md5_groups.items() if len(v) > 1}
    dup_pages = sum(len(v) for v in dup_groups.values())

    # ── spec §6 metrics via the shared core ─────────────────────────────
    snaps = census_wiki(paths)
    known_slugs = page_ids(snaps)
    try:
        from src.wiki.features.slug_aliases import SlugAliasRegistry
        reg = SlugAliasRegistry(root)
        alias_canonical = reg.get_canonical
    except Exception:
        alias_canonical = None

    m1 = metric_broken_links(snaps, known_slugs, alias_canonical=alias_canonical)
    m2_rate, m2_ref, m2_total = metric_deep_reference_rate(snaps, raw_md, project_root=root)
    m6 = metric_synthesis_count(paths)
    m7 = metric_source_fulltext_pollution(snaps)

    # Legacy raw-referenced tap rate (source pages only — legacy measure)
    referenced_raw: set[str] = set()
    for snap in snaps:
        for src in snap.sources:
            referenced_raw.add(_normalize(src).lstrip("./"))
    raw_abs = {_normalize(str(p)) for p in raw_md}
    legacy_tap = sum(1 for r in referenced_raw if any(r in s or s in r for s in raw_abs))

    print(f"raw_files            {len(raw_files)}")
    print(f"raw_md               {len(raw_md)}")
    print(f"wiki_pages_total     {total}")
    for t in ("source", "entity", "concept", "synthesis"):
        print(f"  type_{t}           {per_type[t]}")
    print(f"coverage_ratio       {total / len(raw_md) * 100:.1f}  (wiki_pages/raw_md, >100% by design)")
    print(f"referenced_raw_hits  {legacy_tap}")
    print(f"raw_tap_rate_pct     {legacy_tap / len(raw_md) * 100:.1f}  (legacy, source-pages only)")
    print(f"M1_links_total       {m1.total_links}")
    print(f"M1_broken_links      {m1.broken_links}")
    print(f"M1_broken_rate_pct   {m1.rate * 100:.1f}")
    print(f"M2_deep_ref_rate_pct {m2_rate * 100:.1f}  ({m2_ref}/{m2_total})")
    print(f"M6_synthesis_pages   {m6}")
    print(f"M7_source_fulltext   {m7}")
    print(f"empty_sources_pages  {empty_sources}")
    print(f"empty_relations_pages {empty_relations}")
    print(f"grade_C_pages        {grade_c}")
    print(f"placeholder_pages    {placeholder}")
    print(f"stub_pages           {stub}")
    print(f"legacy_tag_pages     {legacy_tag_pages}")
    print(f"illegal_relation_pages {illegal_relation_pages}")
    print(f"dup_groups           {len(dup_groups)}")
    print(f"dup_pages_involved   {dup_pages}")
    print(f"index_md_present     {(wiki_root / 'index.md').exists()}")

    if json_out:
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "project": root.name,
            "metrics": {
                "M1_broken_rate": round(m1.rate, 4),
                "M1_links_total": m1.total_links,
                "M1_broken_links": m1.broken_links,
                "M2_deep_ref_rate": round(m2_rate, 4),
                "M2_referenced_raw": m2_ref,
                "M2_total_raw": m2_total,
                "M6_synthesis_pages": m6,
                "M7_source_fulltext": m7,
                "M8_legacy_tag_pages": legacy_tag_pages,
                "M9_illegal_relation_pages": illegal_relation_pages,
                "M10a_raw_md": len(raw_md),
            },
            "counts": {
                "raw_files": len(raw_files),
                "raw_md": len(raw_md),
                "wiki_pages_total": total,
                "per_type": per_type,
                "stub_pages": stub,
                "grade_C": grade_c,
                "empty_sources": empty_sources,
                "placeholder_pages": placeholder,
                "dup_groups": len(dup_groups),
                "index_entries": _count_index(wiki_root),
            },
        }
        out = Path(json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"baseline_json        {out}")


def _count_index(wiki_root: Path) -> int:
    index = wiki_root / "index.md"
    if not index.exists():
        return 0
    return sum(1 for line in index.read_text(encoding="utf-8", errors="replace").splitlines()
               if line.strip().startswith("- **"))


if __name__ == "__main__":
    main()
