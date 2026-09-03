"""Scan novel-wiki for duplicate page titles (same title, multiple IDs).

wiki-repair-novel-wiki §6: groups pages by `title` field; flags any group
with more than one ID. Output is JSON suitable for downstream merge /
disambiguation decisions.

Usage:
    python scripts/scan_duplicate_titles.py [<wiki_root>] [--out PATH]

    # default wiki_root = ./knowledge/novel-wiki/wiki
    # default --out     = ./knowledge/novel-wiki/.index/quality/duplicate-titles-YYYYMMDD.json

The script is read-only.
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WIKI_ROOT = REPO_ROOT / "knowledge" / "novel-wiki" / "wiki"
DEFAULT_OUT = REPO_ROOT / "knowledge" / "novel-wiki" / ".index" / "quality"


def _read_frontmatter_title(text: str) -> tuple[str | None, str | None]:
    """Extract (id, title) from the first Frontmatter block. Robust to BOM."""
    # strip UTF-8 BOM if present
    if text.startswith("﻿"):
        text = text[1:]
    if not text.startswith("---\n"):
        return None, None
    end = text.find("\n---", 4)
    if end < 0:
        return None, None
    fm_body = text[4:end]
    pid: str | None = None
    title: str | None = None
    for line in fm_body.split("\n"):
        if line.startswith("id:"):
            pid = line[3:].strip()
        elif line.startswith("title:"):
            title = line[6:].strip()
    return pid, title


def scan(wiki_root: Path) -> list[dict]:
    title_groups: dict[str, list[dict]] = defaultdict(list)
    for md in sorted(wiki_root.rglob("*.md")):
        rel = md.relative_to(wiki_root)
        if len(rel.parts) == 1 and rel.name in {"index.md", "log.md"}:
            continue
        if rel.parts[0] not in {"concepts", "sources", "entities", "synthesis", "_stubs"}:
            continue
        try:
            text = md.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = md.read_bytes().decode("utf-8", errors="replace")
        pid, title = _read_frontmatter_title(text)
        if not title or not pid:
            continue
        title_groups[title].append({
            "id": pid,
            "path": str(rel).replace("\\", "/"),
            "size_bytes": md.stat().st_size,
        })
    # only return groups with duplicates
    return [
        {"title": t, "count": len(pages), "pages": pages}
        for t, pages in title_groups.items()
        if len(pages) > 1
    ]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("wiki_root", nargs="?", type=Path, default=DEFAULT_WIKI_ROOT)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.wiki_root.is_dir():
        print(f"error: {args.wiki_root} not a directory", file=sys.stderr)
        return 2

    groups = scan(args.wiki_root)
    summary = {
        "scanned_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "wiki_root": str(args.wiki_root),
        "total_duplicate_groups": len(groups),
        "total_duplicate_pages": sum(g["count"] for g in groups),
        "groups": sorted(groups, key=lambda g: -g["count"]),
    }
    out = args.out
    if out is None:
        ts = datetime.datetime.now().strftime("%Y%m%d")
        out = DEFAULT_OUT / f"duplicate-titles-{ts}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Duplicate groups: {len(groups)}  Total dup pages: {summary['total_duplicate_pages']}")
    print(f"Written: {out}")
    # Show top 5 by count
    for g in summary["groups"][:5]:
        print(f"  [{g['count']}x] {g['title']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
