"""rebuild_index.py — Phase 0.3: regenerate wiki/index.md from disk pages.

The on-disk catalog drifted (novel-wiki index.md has 15 entries vs 382
pages), producing 367 LINT-ORPHAN warnings that drown the gate. This
script rewrites index.md as a flat catalog of every page currently on
disk (skips log.md / index.md themselves), atomically.

Usage:
    python scripts/rebuild_index.py <project_root> [--dry-run]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.lib.write_hooks import safe_write  # noqa: E402
from src.wiki.core.paths import WikiPaths  # noqa: E402
from src.wiki.features.metrics import census_wiki  # noqa: E402

INDEX_HEADER = "# Wiki Index\n\n"
TYPE_ORDER = {"source": 0, "entity": 1, "concept": 2, "synthesis": 3}


def build_index_lines(paths: WikiPaths) -> list[str]:
    """Return sorted ``- **slug** (type) — title`` lines for all pages."""
    snaps = census_wiki(paths)
    snaps.sort(key=lambda s: (TYPE_ORDER.get(s.page_type, 9), s.id))
    lines = [INDEX_HEADER]
    for s in snaps:
        title = _first_line_title(s)
        lines.append(f"- **{s.id}** ({s.page_type}) — {title}\n")
    return lines


def _first_line_title(snap) -> str:
    """Title from frontmatter if present, else first heading / filename."""
    m = _search_title(snap.raw_frontmatter)
    if m:
        return m
    for line in snap.body.splitlines():
        if line.startswith("#"):
            return line.lstrip("# ").strip()
    return snap.path.stem


def _search_title(fm: str) -> str | None:
    import re
    m = re.search(r"(?m)^title:[ \t]*'?([^'\n]*)'?", fm)
    return m.group(1).strip() if m else None


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: rebuild_index.py <project_root> [--dry-run]")
        sys.exit(2)
    root = Path(sys.argv[1])
    dry_run = "--dry-run" in sys.argv
    paths = WikiPaths(root)
    lines = build_index_lines(paths)
    if dry_run:
        print(f"[dry-run] would write {len(lines) - 1} entries to {paths.llm_wiki_index}")
        return
    content = "".join(lines)
    safe_write(paths.llm_wiki_index, content)
    print(f"wrote {len(lines) - 1} entries to {paths.llm_wiki_index}")


if __name__ == "__main__":
    main()
