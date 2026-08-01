#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Migrate legacy ENGLISH tag prefixes to current CHINESE prefixes in wiki frontmatter.

Mapping (legacy -> current):
    genre->题材, func->功能, char->角色, event->事件, mood->情绪,
    entity->实体, scene_phase->场景阶段, status->状态
    (素材/ and 可信度/ are already Chinese — no mapping for them.)

Scope:
    Scans ``<wiki_root>/wiki/{sources,entities,concepts,synthesis}/*.md`` and
    rewrites ``tags:`` list entries of the form ``<legacy>/<name>`` to the
    mapped Chinese prefix.

Rewrite method (CRITICAL — do NOT YAML round-trip):
    A full YAML parse->dump would reformat the entire frontmatter and create
    noisy diffs across every file. Instead we operate on the raw file text:

      * Read / write in BINARY mode (``newline=""`` equivalent) so CRLF line
        endings and every unrelated byte are preserved verbatim.
      * Split into lines with ``splitlines(keepends=True)``.
      * Only lines in the page's ``tags:`` list block that match
        ``^(\s*-\s*)(genre|func|char|event|mood|entity|scene_phase|status)/(.*)$``
        are touched. ``re.sub`` with a callback replaces ONLY the prefix
        (``group1 + chinese + "/" + group3``); indentation, the suffix, and the
        line ending (LF or CRLF) pass through untouched.

Dedup:
    If a page already carries BOTH ``题材/玄幻`` and ``genre/玄幻``, migration
    would produce two identical ``题材/玄幻`` entries. Within a page's tags
    list, a migrated line that collides with a value already kept is dropped
    (collapsed to one). Only duplicates produced by (or colliding with) a
    migrated tag are collapsed — pre-existing duplicate Chinese tags are left
    alone so files that need no migration are never touched.

Safety:
    SAFE BY DEFAULT — running without ``--apply`` only reports; nothing is
    written. (The real novel-wiki must be migrated with ``--apply`` only after
    reviewing the dry-run output.)

Usage:
    python scripts/migrate_legacy_tags.py                          # dry-run (default)
    python scripts/migrate_legacy_tags.py --dry-run                # same
    python scripts/migrate_legacy_tags.py --apply                  # rewrite in place
    python scripts/migrate_legacy_tags.py path/to/project --apply  # custom root
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# legacy prefix -> current Chinese prefix
LEGACY_TO_CHINESE = {
    "genre": "题材",
    "func": "功能",
    "char": "角色",
    "event": "事件",
    "mood": "情绪",
    "entity": "实体",
    "scene_phase": "场景阶段",
    "status": "状态",
}

# Exact rewrite pattern. Applied per line (the string is one logical line
# including its trailing newline). ``$`` matches at the end of the string or
# just before the final ``\n``, so ``(.*)`` captures the raw suffix (which for
# CRLF files still ends in ``\r``) and the trailing ``\n`` is NOT part of the
# match — re.sub therefore preserves the line ending byte-for-byte.
_TAG_RE = re.compile(r"^(\s*-\s*)(genre|func|char|event|mood|entity|scene_phase|status)/(.*)$")
# Any YAML list item (used to recognize non-legacy tags for dedup bookkeeping).
_LIST_RE = re.compile(r"^(\s*-\s*)(.*)$")

WIKI_SUBDIRS = ("sources", "entities", "concepts", "synthesis")


def _frontmatter_bounds(lines: list[str]) -> tuple[int, int] | None:
    """Return ``(start, end)`` indexes of the frontmatter block, or ``None``.

    ``start`` is the line after the opening ``---``, ``end`` is the index of
    the closing ``---`` line (exclusive range ``[start, end)``).
    """
    if not lines or lines[0].strip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return 1, i
    return None


def _find_tags_key(lines: list[str], fm_start: int, fm_end: int) -> int | None:
    """Index of the top-level ``tags:`` key line inside frontmatter, or ``None``."""
    for i in range(fm_start, fm_end):
        stripped = lines[i].strip()
        if stripped == "tags:" or stripped.startswith("tags:"):
            return i
    return None


def _tags_block_end(lines: list[str], start: int, fm_end: int) -> int:
    """One past the last contiguous ``- item`` line after the ``tags:`` key."""
    j = start
    while j < fm_end:
        m = _LIST_RE.match(lines[j])
        if m and m.group(2).strip() and not lines[j].lstrip().startswith("---"):
            j += 1
        else:
            break
    return j


def migrate_file_text(text: str) -> tuple[str, dict]:
    """Migrate legacy tags in one page's text.

    Returns ``(new_text, stats)`` where stats is
    ``{"rewrites": int, "collapsed": int, "changed": bool,
       "changes": [(old_line, new_line_or_None), ...]}``.
    ``changes`` lists the rewritten/collapsed tag lines (for dry-run examples);
    ``new_line_or_None`` is ``None`` for a collapsed (dropped) line.
    """
    stats = {"rewrites": 0, "collapsed": 0, "changed": False, "changes": []}
    lines = text.splitlines(keepends=True)
    bounds = _frontmatter_bounds(lines)
    if bounds is None:
        return text, stats
    fm_start, fm_end = bounds
    key = _find_tags_key(lines, fm_start, fm_end)
    if key is None:
        return text, stats
    block_end = _tags_block_end(lines, key + 1, fm_end)

    kept_values: set[str] = set()          # canonical tag values already kept
    migration_produced: set[str] = set()   # kept values that came from a migrated legacy tag

    new_block: list[str] = []
    for i in range(key + 1, block_end):
        line = lines[i]
        m = _TAG_RE.match(line)
        if m:
            chinese = LEGACY_TO_CHINESE[m.group(2)]
            canon = (chinese + "/" + m.group(3)).rstrip("\r\n ")
            if canon in kept_values:
                stats["collapsed"] += 1
                stats["changes"].append((line.strip(), None))
                continue  # drop migrated line — it duplicates an existing tag
            new_line = _TAG_RE.sub(
                lambda mm: mm.group(1) + LEGACY_TO_CHINESE[mm.group(2)] + "/" + mm.group(3),
                line,
            )
            new_block.append(new_line)
            kept_values.add(canon)
            migration_produced.add(canon)
            stats["rewrites"] += 1
            stats["changes"].append((line.strip(), new_line.strip()))
            continue
        lm = _LIST_RE.match(line)
        if lm:
            canon = lm.group(2).rstrip("\r\n ")
            if canon in kept_values and canon in migration_produced:
                # Pre-existing Chinese tag that duplicates a migration result.
                stats["collapsed"] += 1
                stats["changes"].append((line.strip(), None))
                continue
            new_block.append(line)
            kept_values.add(canon)
            continue
        # Defensive: a non-list line inside the block (should not happen).
        new_block.append(line)

    new_lines = lines[: key + 1] + new_block + lines[block_end:]
    new_text = "".join(new_lines)
    stats["changed"] = new_text != text
    return new_text, stats


def _read_text(path: Path) -> str:
    """Read in binary then decode so CRLF/LF line endings are preserved."""
    return path.read_bytes().decode("utf-8")


def _write_text(path: Path, text: str) -> None:
    """Encode then write in binary so no newline translation occurs."""
    path.write_bytes(text.encode("utf-8"))


def process_file(path: Path, apply_mode: bool) -> dict:
    """Migrate one file. Returns stats. Writes only when ``apply_mode``."""
    text = _read_text(path)
    new_text, stats = migrate_file_text(text)
    if stats["changed"] and apply_mode:
        _write_text(path, new_text)
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Migrate legacy English tag prefixes to Chinese in wiki frontmatter.",
    )
    ap.add_argument(
        "wiki_root",
        nargs="?",
        default="knowledge/novel-wiki",
        help="Project root containing wiki/ (default: knowledge/novel-wiki)",
    )
    group = ap.add_mutually_exclusive_group()
    group.add_argument(
        "--dry-run",
        action="store_true",
        help="Report only; make no changes (this is the default)",
    )
    group.add_argument(
        "--apply",
        action="store_true",
        help="Rewrite legacy tag prefixes in place",
    )
    args = ap.parse_args()

    root = Path(args.wiki_root)
    wiki = root / "wiki"
    if not wiki.is_dir():
        print(f"[migrate] error: no wiki directory at {wiki}", file=sys.stderr)
        return 1

    files = []
    for sub in WIKI_SUBDIRS:
        d = wiki / sub
        if d.is_dir():
            files.extend(sorted(d.glob("*.md")))
    files = sorted(files)

    total_rewrites = total_collapsed = files_with_legacy = 0
    examples: list[str] = []
    for path in files:
        stats = process_file(path, apply_mode=args.apply)
        if not stats["changed"]:
            continue
        files_with_legacy += 1
        total_rewrites += stats["rewrites"]
        total_collapsed += stats["collapsed"]
        if not args.apply and len(examples) < 8:
            for old, new in stats["changes"][:3]:
                if new is None:
                    examples.append(f"{path.name}: {old}  ->  <collapsed duplicate>")
                else:
                    examples.append(f"{path.name}: {old}  ->  {new}")

    print(f"[migrate] scanned {len(files)} files under {wiki}")
    print(f"[migrate] {files_with_legacy} files contain legacy tags")
    print(f"[migrate] tags rewritten: {total_rewrites}, duplicate tags collapsed: {total_collapsed}")
    if examples:
        print("[migrate] example rewrites (dry-run):")
        for e in examples:
            print(f"  {e}")

    if args.apply:
        print(f"[migrate] WROTE {files_with_legacy} files")
    else:
        print("[migrate] dry-run — no changes made (pass --apply to rewrite)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
