"""Detect duplicate Frontmatter delimiters in novel-wiki V4 wiki pages.

wiki-repair-novel-wiki §3.1: V4 validator does not detect duplicate
Frontmatter (when a file has two `---\\n...\\n---` blocks separated by
only blank lines or comments). This script fills the gap.

A page is flagged when:
- The file starts with `---\\n`
- The first Frontmatter block parses cleanly
- After the closing `---\\n`, within the next 200 chars, another `---\\n`
  delimiter appears

Usage:
    python scripts/check_duplicate_frontmatter.py [<wiki_root>]

    # default wiki_root = ./knowledge/novel-wiki/wiki

The script is read-only. Output is plain text (one path per line) so it
can be redirected to `.index/quality/duplicate-frontmatter-YYYYMMDD.txt`.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WIKI_ROOT = REPO_ROOT / "knowledge" / "novel-wiki" / "wiki"

TYPE_DIRS = {"concepts", "sources", "entities", "synthesis", "_stubs"}
RESERVED_FILES = {"index.md", "log.md"}


def has_duplicate_frontmatter(text: str) -> bool:
    """Return True if the file has duplicate Frontmatter delimiters.

    Heuristic: after the first Frontmatter closing `---`, look at the
    next 5 lines. If another standalone `---` appears among them (with
    only blank lines or HTML comments in between), this is a duplicate
    Frontmatter delimiter. Horizontal Markdown rules (which also use
    `---`) sit further down the body and are excluded by this window.
    """
    if not text.startswith("---\n"):
        return False
    # Find end of first FM block (closing `---` line)
    end = text.find("\n---", 4)
    if end < 0:
        return False
    # Skip past the closing `---` line's newline
    close_newline = text.find("\n", end + 4)
    if close_newline < 0:
        return False
    after = text[close_newline + 1:]
    # Inspect the next 5 lines
    next_lines = after.split("\n")[:5]
    for line in next_lines:
        stripped = line.strip()
        if stripped == "---":
            return True
        # Stop scanning on the first non-blank, non-comment line:
        # any `---` past this point is body content (horizontal rule).
        if stripped and not stripped.startswith("<!--"):
            return False
    return False


def scan(wiki_root: Path) -> list[Path]:
    flagged: list[Path] = []
    for md in sorted(wiki_root.rglob("*.md")):
        rel = md.relative_to(wiki_root)
        if len(rel.parts) == 1 and rel.name in RESERVED_FILES:
            continue
        if rel.parts[0] not in TYPE_DIRS:
            continue
        try:
            text = md.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # try with BOM-stripping
            text = md.read_bytes().decode("utf-8-sig", errors="replace")
        if has_duplicate_frontmatter(text):
            flagged.append(md)
    return flagged


def main(argv: list[str]) -> int:
    wiki_root = Path(argv[1]) if len(argv) > 1 else DEFAULT_WIKI_ROOT
    if not wiki_root.is_dir():
        print(f"error: {wiki_root} is not a directory", file=sys.stderr)
        return 2
    flagged = scan(wiki_root)
    for md in flagged:
        try:
            rel = md.relative_to(wiki_root)
        except ValueError:
            rel = md
        print(str(rel).replace("\\", "/"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
