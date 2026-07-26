"""One-shot migration: register CJK aliases for existing pinyin-slug pages.

After the 2026-07-26 CJK cut-over, slugify() preserves Chinese
characters verbatim. Existing wiki pages were created BEFORE the
cut-over with **pinyin slugs** (e.g. ``wangluo-wenxue.md`` for the
concept 网络文学). Going forward, the LLM will emit CJK slugs
(``网络文学``) directly, which would otherwise create a duplicate
page for the same concept.

This migration registers forward aliases so references using the
new CJK slug resolve to the existing pinyin page:

    网络文学  →  wangluo-wenxue  (.md exists, references resolve)

Implementation:
  1. Walk all wiki pages; parse frontmatter title.
  2. Compute the new-CJK slug of the title using the current
     ``slugify()`` (which preserves CJK).
  3. If that slug differs from the page's existing pinyin id,
     register ``new_cjk_slug → existing_pinyin_id`` in
     ``.llm-wiki/slug_aliases.json``.
  4. Skip pages whose title slugifies to the same id (already
     CJK-friendly) and pages whose title has no CJK content.

The script is idempotent + dry-run by default.

Usage:
    python scripts/migrate_pinyin_to_cjk_aliases.py [wiki_root]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml


FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
RESERVED_IDS = {"index", "log"}
CJK_BASIC = ("一", "鿿")


def _has_cjk(s: str) -> bool:
    return any(CJK_BASIC[0] <= ch <= CJK_BASIC[1] for ch in s)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument(
        "wiki_root",
        nargs="?",
        default=r"E:\2026-7-21\ruflo-kb\knowledge\novel-wiki",
        help="Path to the project directory (containing .llm-wiki/). "
             "Defaults to novel-wiki.",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Persist HIGH confidence aliases to .llm-wiki/slug_aliases.json. "
             "Without this flag the script is dry-run only.",
    )
    args = parser.parse_args()

    project_root = Path(args.wiki_root)
    wiki_root = project_root / "wiki"
    if not wiki_root.exists():
        print(f"ERROR: {wiki_root} not found", file=sys.stderr)
        return 1

    # Lazy-import the new slugify so we test against the live code,
    # not a snapshot.
    sys.path.insert(0, str(project_root.parent.parent))  # ensure src/ on path
    from src.utils.slugify import slugify
    from src.wiki.features.slug_aliases import SlugAliasRegistry

    md_files = [f for f in wiki_root.rglob("*.md") if f.stem not in RESERVED_IDS]
    proposed: list[tuple[str, str, str]] = []  # (existing_pinyin_id, new_cjk_slug, page_title)

    for f in md_files:
        text = f.read_text(encoding="utf-8")
        m = FRONTMATTER_RE.match(text)
        if not m:
            continue
        try:
            fm = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            continue
        page_id = fm.get("id") or f.stem
        title = fm.get("title")
        if not title or not isinstance(title, str):
            continue
        if not _has_cjk(title):
            continue  # Pure-ASCII titles: new slugify produces same pinyin
                     # form, no alias needed.
        new_slug = slugify(title)
        if not new_slug or new_slug == page_id:
            continue  # Title slugifies to existing id (or empty): no alias needed.
        proposed.append((page_id, new_slug, title))

    print("=" * 72)
    print(f"CJK alias migration — project: {project_root}")
    print("=" * 72)
    print(f"\nTotal pages scanned: {len(md_files)}")
    print(f"Pages whose CJK slug differs from existing id: {len(proposed)}\n")

    if not proposed:
        print("Nothing to do.")
        return 0

    # Sort: alphabetical for predictable output.
    proposed.sort()

    print("--- PROPOSED ALIASES ---")
    for page_id, new_slug, title in proposed:
        print(f"  {new_slug!r:40s} → {page_id!r:40s}  (title={title!r})")

    if not args.apply:
        print("\n(Dry run — re-run with --apply to persist.)")
        return 0

    reg = SlugAliasRegistry(project_root)
    added = 0
    skipped = 0
    for page_id, new_slug, _ in proposed:
        # Don't clobber if an alias is already registered.
        existing = reg.get_canonical(new_slug)
        if existing == page_id:
            skipped += 1
            continue
        if existing is not None and existing != page_id:
            print(f"  ! {new_slug!r} already mapped to {existing!r}; "
                  f"not overriding with {page_id!r}")
            skipped += 1
            continue
        reg.add(new_slug, page_id)
        added += 1
        print(f"  + {new_slug!r} → {page_id!r}")
    reg.save()

    print(f"\nSaved {added} new alias(es), skipped {skipped}.")
    print(f"Alias registry: {project_root}/.llm-wiki/slug_aliases.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
