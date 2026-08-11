"""Phase 0 baseline audit — read-only stats for a ruflo-kb wiki.

Computes counts used by docs/guides/novel-wiki-ingest-spec.md 第 10 节
(验收指标): raw file count, wiki page count per type, coverage,
empty-sources / empty-relations pages, grade-C pages, body-md5 duplicate
groups (placeholder-body pollution), and per-dir page tallies.

Usage:
    env PYTHONIOENCODING=utf-8 python scripts/audit_wiki_baseline.py <wiki_root>

Output is ASCII-only on stdout (counts + ASCII labels) so it is robust to
Windows console codepages. All Chinese page ids are intentionally NOT
printed here; use grep/glob for UTF-8 detail.
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path


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
    m = re.search(rf"(?m)^\s*{key}:\s*(.*)$", fm)
    if not m:
        return False
    rest = m.group(1).strip()
    if rest.startswith("["):
        return rest.strip("[]") != ""
    if rest:
        return True
    tail = fm[m.end():]
    return bool(re.match(r"\s*-\s*\S", tail))


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: audit_wiki_baseline.py <wiki_root>")
        sys.exit(2)
    root = Path(sys.argv[1])
    raw_root = root / "raw"
    wiki_root = root / "wiki"

    raw_files = [p for p in raw_root.rglob("*") if p.is_file()]

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
    md5_groups: dict[str, list[str]] = {}
    referenced_raw: set[str] = set()
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
            if "占位" in body or "系统占位" in body:
                placeholder += 1
            # Collect raw paths mentioned in the `sources` list field
            sm = re.search(rf"(?m)^sources:\s*(.*)$", fm)
            if sm:
                seg = fm[sm.start():]
                seg = seg.split("\n\n", 1)[0]
                for line in re.findall(r"(?m)^\s*-\s*(.+)$", seg):
                    p = line.strip().strip('"').strip("'").replace("\\", "/")
                    if p:
                        referenced_raw.add(p)
            if body.strip():
                h = hashlib.md5(body.encode("utf-8")).hexdigest()
                md5_groups.setdefault(h, []).append(str(f))

    dup_groups = {h: v for h, v in md5_groups.items() if len(v) > 1}
    dup_pages = sum(len(v) for v in dup_groups.values())

    raw_stems = {str(p).replace("\\", "/") for p in raw_files}
    referenced_hits = sum(
        1 for r in referenced_raw if any(r in s or s in r for s in raw_stems)
    )
    tap_rate = referenced_hits / len(raw_files) if raw_files else 0.0

    print(f"raw_files            {len(raw_files)}")
    print(f"wiki_pages_total     {total}")
    for t in ("source", "entity", "concept", "synthesis"):
        print(f"  type_{t}           {per_type[t]}")
    print(f"coverage_ratio       {total / len(raw_files) * 100:.1f}  (wiki_pages/raw, >100% by design)")
    print(f"referenced_raw_hits  {referenced_hits}")
    print(f"raw_tap_rate_pct     {tap_rate * 100:.1f}")
    print(f"empty_sources_pages  {empty_sources}")
    print(f"empty_relations_pages {empty_relations}")
    print(f"grade_C_pages        {grade_c}")
    print(f"placeholder_pages    {placeholder}")
    print(f"dup_groups           {len(dup_groups)}")
    print(f"dup_pages_involved   {dup_pages}")
    print(f"index_md_present     {(wiki_root / 'index.md').exists()}")


if __name__ == "__main__":
    main()
