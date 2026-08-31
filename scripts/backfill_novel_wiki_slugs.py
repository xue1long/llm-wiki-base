"""One-shot migration: backfill missing `slug:` lines on novel-wiki pages.

Decision context (2026-08-31):
    After pruning the V3 template from 16 keys → 10 keys for the novel-wiki
    scope, the remaining derived field `slug` is a write-time injection
    (handled by the writer layer). However, ~64.3% of the existing 4892
    pages were generated before the writer started injecting the slug,
    so they have empty/missing slug lines. This script closes the gap by
    deriving `slug` from the on-disk path (`<type_dir>/<id-without-ext>`).

Slug derivation rules (mirrors `gbrain_slug_for_path`):
    - `wiki/concepts/<id>.md`   → `slug: concepts/<id>`
    - `wiki/sources/<id>.md`    → `slug: sources/<id>`
    - `wiki/synthesis/<id>.md`  → `slug: synthesis/<id>`
    - `wiki/entities/<id>.md`   → `slug: entities/<id>`
    - `wiki/claims/<id>.md`     → `slug: claims/<id>`
    - `wiki/_stubs/<id>.md`     → `slug: _stubs/<id>`

Frontmatter placement:
    The slug line is inserted just BEFORE `created_at:` (per the slim
    template ordering: L1 → derived → optional → timestamps). Existing
    slugs are NEVER overwritten — the writer treats the frontmatter as
    authoritative and would already have a slug here if the page was
    written under the new writer.

Usage:
    python scripts/backfill_novel_wiki_slugs.py [--dry-run] [wiki_root]

    # default wiki_root = ./knowledge/novel-wiki
    # default mode     = --dry-run (safe; no writes)

The script is idempotent: every existing `slug:` line is detected and
skipped; running twice makes zero additional changes the second run.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
SLUG_LINE_RE = re.compile(r"^slug:\s*\S", re.MULTILINE)
CREATED_AT_RE = re.compile(r"^created_at:\s", re.MULTILINE)

RESERVED_FILES = {"index.md", "log.md"}
TYPE_DIRS = {"concepts", "sources", "entities", "synthesis", "claims", "_stubs"}


def derive_slug(md_path: Path, wiki_root: Path) -> str:
    """Return `<type_dir>/<id>` for a page under wiki_root/<type_dir>/<id>.md."""
    rel = md_path.relative_to(wiki_root).with_suffix("")
    parts = rel.parts
    if len(parts) < 2:
        raise ValueError(f"unexpected path layout: {md_path}")
    return "/".join(parts)


def parse_frontmatter(text: str) -> tuple[str, str, str] | None:
    """Return (prefix, fm_body, suffix) if frontmatter present, else None.

    prefix = the leading "---\\n"
    fm_body = everything between the two "---" lines
    suffix = the rest of the file (body) starting with the closing "---\\n"
    """
    m = FRONTMATTER_RE.match(text)
    if not m:
        return None
    return ("---\n", m.group(1), "---\n" + text[m.end():])


def has_slug(fm_body: str) -> bool:
    return bool(SLUG_LINE_RE.search(fm_body))


def insert_slug(fm_body: str, slug: str) -> str:
    """Insert `slug: <slug>` just BEFORE the first `created_at:` line.

    If no `created_at:` line is present, append at the end (frontmatter
    will still be valid YAML; the writer normalizes ordering on next save).
    """
    new_line = f"slug: {slug}\n"
    m = CREATED_AT_RE.search(fm_body)
    if m:
        idx = m.start()
        return fm_body[:idx] + new_line + fm_body[idx:]
    return fm_body.rstrip("\n") + "\n" + new_line


def backfill(wiki_root: Path, dry_run: bool) -> tuple[int, int, int, list[str]]:
    """Returns (scanned, skipped_existing, backfilled, sample_changed_paths)."""
    scanned = 0
    skipped = 0
    backfilled = 0
    samples: list[str] = []
    for md in sorted(wiki_root.rglob("*.md")):
        if md.name in RESERVED_FILES:
            continue
        rel = md.relative_to(wiki_root)
        if rel.parts[0] not in TYPE_DIRS:
            continue
        scanned += 1
        text = md.read_text(encoding="utf-8")
        parsed = parse_frontmatter(text)
        if parsed is None:
            continue
        _, fm_body, suffix = parsed
        if has_slug(fm_body):
            skipped += 1
            continue
        slug = derive_slug(md, wiki_root)
        new_fm = insert_slug(fm_body, slug)
        new_text = f"---\n{new_fm}{suffix}"
        if dry_run:
            if len(samples) < 5:
                samples.append(f"[DRY] {md.relative_to(wiki_root.parent.parent)} ← slug: {slug}")
        else:
            md.write_text(new_text, encoding="utf-8")
        backfilled += 1
    return scanned, skipped, backfilled, samples


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "wiki_root",
        nargs="?",
        default="knowledge/novel-wiki/wiki",
        help="path to wiki/ directory (default: knowledge/novel-wiki/wiki)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="show what would change without writing (default)",
    )
    parser.add_argument(
        "--apply",
        dest="dry_run",
        action="store_false",
        help="actually write the changes (overrides --dry-run)",
    )
    args = parser.parse_args()

    wiki_root = Path(args.wiki_root).resolve()
    if not wiki_root.is_dir():
        print(f"error: not a directory: {wiki_root}", file=sys.stderr)
        return 2

    print(f"[backfill-slugs] wiki_root={wiki_root}")
    print(f"[backfill-slugs] mode={'DRY-RUN' if args.dry_run else 'APPLY'}")
    scanned, skipped, backfilled, samples = backfill(wiki_root, args.dry_run)
    print(f"[backfill-slugs] scanned={scanned} skipped_existing_slug={skipped} "
          f"{'would_backfill' if args.dry_run else 'backfilled'}={backfilled}")
    if samples:
        print("[backfill-slugs] samples:")
        for s in samples:
            print(f"  {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())