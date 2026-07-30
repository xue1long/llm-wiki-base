#!/usr/bin/env python3
"""Normalise ``sources:`` frontmatter fields across all wiki pages.

Scans every ``wiki/{sources,entities,concepts,synthesis}/*.md``,
extracts the ``sources`` YAML list from the frontmatter, and rewrites
each entry to the canonical project-relative form::

    raw/sources/<category>/<filename>.md

with forward slashes.

The canonical path is looked up by matching the filename **stem**
against ``raw/sources/**/*.md`` on disk.  Because the LLM pipeline
already passes the correct absolute path to ``WikiPage.sources``, the
stem is always a reliable key — the script only fixes formatting
(backslashes, absolute prefixes, prose wrapping) and never guesses.

Usage::

    # Dry-run — preview every change (default)
    python scripts/normalize_sources.py knowledge/novel-wiki

    # Apply
    python scripts/normalize_sources.py knowledge/novel-wiki --apply

    # Apply to a single type directory
    python scripts/normalize_sources.py knowledge/novel-wiki --apply --only concepts

Safety:
- ``--dry-run`` is the default; ``--apply`` is required to write.
- Every file is written atomically (temp file + os.replace).
- A stem that matches **zero** or **multiple** raw files is left
  untouched and reported as a warning.
"""

import argparse
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_WIKI_DIRS = ("sources", "entities", "concepts", "synthesis")

# Recognise prose-wrapped paths like:
#   **原始文件路径**：`raw/sources/01_新手入门/foo.md`
#   - **来源载体**：飞书云文档（...）
#   - raw\sources\02_进阶技巧\bar.md
_PATHISH = re.compile(
    r"(?:raw[/\\]sources[/\\][^\s`)}\]]+\.md)",
    re.IGNORECASE,
)


def _extract_stem(entry: str) -> Optional[str]:
    """Best-effort extraction of a filename stem from a *sources* entry.

    Returns ``None`` when the entry does not appear to reference a raw
    file (e.g. a prose-only note like "飞书云文档分享链接").
    """
    entry = entry.strip()
    if not entry:
        return None

    # Already a clean path-like string
    if "raw" in entry.lower() and entry.endswith(".md"):
        # Strip backslash, quotes, bold markers, list markers
        cleaned = entry.replace("\\", "/").rstrip(".")
        # Handle prose patterns:  **标签**：`path`
        m = _PATHISH.search(cleaned)
        if m:
            cleaned = m.group(0)
        stem = Path(cleaned).stem
        return stem if stem else None

    # Try to see if it looks like a path at all
    if entry.endswith(".md"):
        stem = Path(entry.replace("\\", "/")).stem
        return stem if stem else None

    return None


def _build_stem_index(raw_sources_dir: Path) -> dict[str, list[Path]]:
    """Build ``{stem: [Path, ...]}`` index of every .md file under *raw_sources_dir*."""
    index: dict[str, list[Path]] = defaultdict(list)
    for md in raw_sources_dir.rglob("*.md"):
        index[md.stem].append(md)
    return dict(index)


def _canonical_path(raw_file: Path, raw_sources_dir: Path) -> str:
    """Return ``raw/sources/<relative-path>`` with forward slashes."""
    # raw_sources_dir is e.g. knowledge/novel-wiki/raw/sources
    # We want raw/sources/<category>/file.md → relative to project root
    project_root = raw_sources_dir.parent.parent  # knowledge/novel-wiki
    rel = raw_file.relative_to(project_root)
    return rel.as_posix()


# ---------------------------------------------------------------------------
# YAML frontmatter (lightweight — no PyYAML dependency)
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

# Match the ``sources:`` list inside YAML frontmatter.  We rewrite the
# whole block so indentation is preserved.
_SOURCES_BLOCK_RE = re.compile(r"(^sources:\s*\n(?:^\s+-.*\n)*)", re.MULTILINE)


def _parse_sources_entries(frontmatter: str) -> list[str]:
    """Extract individual source entries from the frontmatter text."""
    lines = frontmatter.split("\n")
    entries: list[str] = []
    in_sources = False
    for line in lines:
        if line.startswith("sources:"):
            in_sources = True
            continue
        if in_sources:
            stripped = line.strip()
            if stripped.startswith("- "):
                entries.append(stripped[2:].strip())
            elif stripped and not stripped.startswith("-"):
                # Next top-level key — done with sources
                break
    return entries


def _replace_sources_block(frontmatter: str, new_entries: list[str]) -> str:
    """Rewrite the ``sources:`` block with *new_entries*."""
    lines = frontmatter.split("\n")
    result: list[str] = []
    in_sources = False
    skip_until_next_key = False
    for line in lines:
        if line.startswith("sources:"):
            result.append("sources:")
            for e in new_entries:
                result.append(f"  - {e}")
            in_sources = True
            skip_until_next_key = True
            continue
        if skip_until_next_key:
            stripped = line.strip()
            if stripped.startswith("- ") and in_sources:
                continue  # old entry — drop
            if stripped and not stripped.startswith("- "):
                # Next key — stop skipping
                skip_until_next_key = False
                result.append(line)
            # Empty lines while skipping are dropped
            continue
        result.append(line)
    return "\n".join(result)


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def normalise_project(
    project_root: Path,
    *,
    apply: bool = False,
    only: Optional[str] = None,
) -> dict:
    """Run normalisation for one project.

    Returns a summary dict with counts.
    """
    raw_sources_dir = project_root / "raw" / "sources"
    wiki_dir = project_root / "wiki"

    if not raw_sources_dir.is_dir():
        print(f"ERROR: raw/sources/ not found at {raw_sources_dir}", file=sys.stderr)
        sys.exit(1)
    if not wiki_dir.is_dir():
        print(f"ERROR: wiki/ not found at {wiki_dir}", file=sys.stderr)
        sys.exit(1)

    stem_index = _build_stem_index(raw_sources_dir)
    print(f"Indexed {sum(len(v) for v in stem_index.values())} raw files "
          f"({len(stem_index)} unique stems)")

    dirs = [only] if only else list(_WIKI_DIRS)
    stats = {"pages_scanned": 0, "pages_changed": 0, "entries_fixed": 0,
             "entries_kept": 0, "entries_warned": 0, "warnings": []}

    for dir_name in dirs:
        type_dir = wiki_dir / dir_name
        if not type_dir.is_dir():
            continue
        for md_path in sorted(type_dir.glob("*.md")):
            stats["pages_scanned"] += 1
            try:
                changed = _normalise_one_page(
                    md_path, stem_index, raw_sources_dir, apply=apply, stats=stats,
                )
                if changed:
                    stats["pages_changed"] += 1
            except Exception as exc:
                msg = f"ERROR processing {md_path}: {exc}"
                print(msg, file=sys.stderr)
                stats["warnings"].append(msg)

    return stats


def _normalise_one_page(
    md_path: Path,
    stem_index: dict[str, list[Path]],
    raw_sources_dir: Path,
    *,
    apply: bool,
    stats: dict,
) -> bool:
    """Normalise one wiki page.  Returns True if the file was changed."""
    original = md_path.read_text(encoding="utf-8")

    m = _FRONTMATTER_RE.match(original)
    if not m:
        return False  # no frontmatter — shouldn't happen

    fm_text = m.group(1)
    entries = _parse_sources_entries(fm_text)
    if not entries:
        return False

    new_entries: list[str] = []
    changed = False

    for entry in entries:
        stem = _extract_stem(entry)
        if stem is None:
            # Non-path entry — keep as-is
            new_entries.append(entry)
            stats["entries_kept"] += 1
            continue

        candidates = stem_index.get(stem)
        if not candidates:
            # Zero matches — keep original, warn
            new_entries.append(entry)
            stats["entries_warned"] += 1
            msg = f"WARNING: stem={stem!r} not found in raw/sources/ — {md_path.name}"
            print(msg)
            stats["warnings"].append(msg)
            continue

        if len(candidates) > 1:
            # Multiple matches — try directory-name disambiguation
            entry_norm = entry.replace("\\", "/")
            best = None
            for c in candidates:
                c_rel = _canonical_path(c, raw_sources_dir)
                # Prefer the candidate whose directory appears in the original entry
                if str(c.parent.name) in entry_norm:
                    best = c
                    break
            if best is None:
                best = candidates[0]  # fallback to first
                msg = (f"WARNING: stem={stem!r} has {len(candidates)} matches; "
                       f"using {_canonical_path(best, raw_sources_dir)} — {md_path.name}")
                print(msg)
                stats["warnings"].append(msg)

            canonical = _canonical_path(best, raw_sources_dir)
        else:
            canonical = _canonical_path(candidates[0], raw_sources_dir)

        if entry.replace("\\", "/") != canonical:
            changed = True
            stats["entries_fixed"] += 1
            new_entries.append(canonical)
        else:
            stats["entries_kept"] += 1
            new_entries.append(entry)

    if not changed:
        return False

    new_fm = _replace_sources_block(fm_text, new_entries)
    new_content = original.replace(fm_text, new_fm, 1)

    if apply:
        # Atomic write
        tmp = md_path.with_suffix(md_path.suffix + ".tmp")
        tmp.write_text(new_content, encoding="utf-8")
        os.replace(str(tmp), str(md_path))
    else:
        # Dry-run: show diff-like output
        stem_short = md_path.stem[:50]
        old_entries = [e[:80] for e in entries]
        new_short = [e[:80] for e in new_entries]
        if old_entries != new_short:
            print(f"\n--- {md_path.relative_to(md_path.parents[2])}")
            for old, new in zip(old_entries, new_short):
                if old != new:
                    print(f"  - {old}")
                    print(f"  + {new}")

    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Normalise sources: frontmatter paths in wiki pages",
    )
    parser.add_argument(
        "project", type=str,
        help="Path to project root (e.g. knowledge/novel-wiki)",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually write changes (default: dry-run)",
    )
    parser.add_argument(
        "--only", type=str, choices=list(_WIKI_DIRS),
        help="Process only one wiki type directory",
    )
    args = parser.parse_args()

    project_root = Path(args.project).resolve()
    if not project_root.is_dir():
        print(f"ERROR: {args.project} is not a directory", file=sys.stderr)
        sys.exit(1)

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"=== {mode} :: {project_root} ===\n")

    result = normalise_project(
        project_root,
        apply=args.apply,
        only=args.only,
    )

    print(f"\n--- Summary ---")
    print(f"  Pages scanned:   {result['pages_scanned']}")
    print(f"  Pages changed:   {result['pages_changed']}")
    print(f"  Entries fixed:   {result['entries_fixed']}")
    print(f"  Entries kept:    {result['entries_kept']}")
    print(f"  Entries warned:  {result['entries_warned']}")
    if result["warnings"]:
        print(f"  Warnings:        {len(result['warnings'])}")
    if not args.apply:
        print(f"\n  (dry-run — use --apply to write changes)")


if __name__ == "__main__":
    main()
