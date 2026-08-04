#!/usr/bin/env python3
"""
Data migration script: Convert WikiPage timestamps from Unix ms to ISO 8601.

Usage:
    python scripts/migrate_timestamps.py <wiki_root>

Example:
    python scripts/migrate_timestamps.py ./knowledge/novel-wiki
"""
import sys
from pathlib import Path
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.wiki.core.paths import WikiPaths
from src.wiki.storage.page_writer import read_page, write_page
from src.wiki.core.types import PageType
from src.utils.timestamp import unix_ms_to_iso


def migrate_wiki_page(md_file: Path) -> bool:
    """Migrate a single wiki page's timestamps.

    Returns:
        True if migration was needed, False if already migrated
    """
    try:
        page = read_page(md_file)
    except Exception as e:
        print(f"  [ERROR] Failed to read {md_file}: {e}")
        return False

    changed = False

    # Check if migration is needed
    if isinstance(page.created_at, int):
        page.created_at = unix_ms_to_iso(page.created_at)
        changed = True

    if isinstance(page.updated_at, int):
        page.updated_at = unix_ms_to_iso(page.updated_at)
        changed = True

    if isinstance(page.last_used_at, int):
        page.last_used_at = unix_ms_to_iso(page.last_used_at)
        changed = True

    if isinstance(page.zombie_since, int):
        page.zombie_since = unix_ms_to_iso(page.zombie_since)
        changed = True

    if changed:
        try:
            write_page(None, page)  # write_page will derive paths from page metadata
            return True
        except Exception as e:
            print(f"  [ERROR] Failed to write {md_file}: {e}")
            return False

    return False


def migrate_wiki_directory(wiki_root: Path) -> dict:
    """Migrate all wiki pages under a directory.

    Returns:
        Stats dict with counts
    """
    paths = WikiPaths(wiki_root)

    stats = {
        "total": 0,
        "migrated": 0,
        "skipped": 0,
        "errors": 0,
    }

    # Migrate pages in each typed directory
    for page_type, dir_prop in [
        (PageType.SOURCE, "wiki_sources"),
        (PageType.ENTITY, "wiki_entities"),
        (PageType.CONCEPT, "wiki_concepts"),
        (PageType.SYNTHESIS, "wiki_synthesis"),
        (PageType.CLAIM, "wiki_claims"),
        (PageType.DECISION, "wiki_decisions"),
    ]:
        dir_path = getattr(paths, dir_prop, None)
        if dir_path is None or not dir_path.exists():
            continue

        print(f"\nProcessing {dir_prop}/...")
        for md_file in sorted(dir_path.glob("*.md")):
            stats["total"] += 1
            result = migrate_wiki_page(md_file)
            if result:
                stats["migrated"] += 1
                print(f"  [MIGRATED] {md_file.name}")
            else:
                stats["skipped"] += 1

    return stats


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    wiki_root = Path(sys.argv[1])
    if not wiki_root.exists():
        print(f"Error: Path does not exist: {wiki_root}")
        sys.exit(1)

    print(f"Migrating timestamps in: {wiki_root}")
    stats = migrate_wiki_directory(wiki_root)

    print(f"\n=== Migration Summary ===")
    print(f"Total pages:    {stats['total']}")
    print(f"Migrated:       {stats['migrated']}")
    print(f"Skipped:        {stats['skipped']}")
    print(f"Errors:         {stats['errors']}")

    if stats["migrated"] > 0:
        print(f"\n✅ Migration complete!")
    else:
        print(f"\n✅ No migration needed (already using ISO 8601)")


if __name__ == "__main__":
    main()
