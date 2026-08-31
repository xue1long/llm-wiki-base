"""Fast fixup: V3 templates said '素材/ugc is DELETED, expressed via
credibility/ugc (has_credibility)'. Our initial V4 migration script
omitted the 素材/ → credibility/ mapping, so 1693 wiki pages kept
'素材/ugc' in their tags list.

This is a fast plain-text fixup (no yaml round-trip per file) — replaces
"  - 素材/ugc\n" with nothing in frontmatter tags, and prepends a
relations edge:

  - target: credibility/ugc
    type: has_credibility
    weight: 1.0

Use --dry-run first, then --apply.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


# Match frontmatter tags block ending (start of relations: or end of FM).
TAG_LINE = re.compile(r"^(\s*-\s*)(素材/[^\n]+)\n", re.MULTILINE)


def migrate_file(path: Path, dry_run: bool) -> tuple[int, int]:
    """Return (n_tags_removed, n_relations_added). 0,0 means no change."""
    text = path.read_text(encoding="utf-8")
    if "素材/" not in text:
        return 0, 0

    # Split into frontmatter and body
    if not text.startswith("---\n"):
        return 0, 0
    end = text.find("\n---\n", 4)
    if end < 0:
        # Malformed: closing --- glued to value
        m = re.search(r"\n---(\n|\Z)", text[4:])
        if not m:
            return 0, 0
        end = m.start() + 4
    fm_text = text[4:end]
    body = text[end:]

    # Find all 素材/ tags in the tags block
    tag_matches = TAG_LINE.findall(fm_text)
    if not tag_matches:
        return 0, 0

    # Extract the suffix after 素材/ (the name)
    names = []
    for prefix, full_tag in tag_matches:
        name = full_tag[len("素材/"):].strip()
        if name and name not in names:
            names.append(name)

    # Remove the tag lines
    new_fm = TAG_LINE.sub("", fm_text)

    # Determine if relations: section exists
    has_relations_section = re.search(r"^relations:\s*\[?\s*$", new_fm, re.MULTILINE) or \
                            re.search(r"^relations:\s*\[[^\]]*\]", new_fm, re.MULTILINE) or \
                            re.search(r"^relations:\s*$", new_fm, re.MULTILINE)

    if has_relations_section:
        # Find the relations: line and append after it (if non-empty) or replace with full block
        # For simplicity, replace relations: [] with full relations block
        new_relation_entries = []
        for name in names:
            new_relation_entries.append(
                f"  - target: credibility/{name}\n"
                f"    type: has_credibility\n"
                f"    weight: 1.0"
            )
        new_block = "relations:\n" + "\n".join(new_relation_entries) + "\n"
        new_fm = re.sub(
            r"^relations:.*?(?=\n[a-z_]+:|\Z)",
            new_block,
            new_fm,
            count=1,
            flags=re.MULTILINE | re.DOTALL,
        )
    else:
        # No relations section yet — add one before sources/created_at/updated_at
        relation_block_lines = ["relations:"]
        for name in names:
            relation_block_lines.append(f"  - target: credibility/{name}")
            relation_block_lines.append(f"    type: has_credibility")
            relation_block_lines.append(f"    weight: 1.0")
        relation_block_lines.append("")
        relation_block = "\n".join(relation_block_lines)

        # Insert before id/title/type/sources/created_at/updated_at
        # Find the first such line and insert before it
        m = re.search(r"^(id|title|type|sources|created_at|updated_at):", new_fm, re.MULTILINE)
        if m:
            new_fm = new_fm[:m.start()] + relation_block + "\n" + new_fm[m.start():]
        else:
            # fallback: append before the closing --- boundary
            new_fm = new_fm.rstrip() + "\n" + relation_block

    new_text = f"---\n{new_fm}\n---{body}"

    if not dry_run:
        path.write_text(new_text, encoding="utf-8")

    return len(tag_matches), len(names)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("wiki_root", nargs="?", default="knowledge/novel-wiki")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--apply", dest="dry_run", action="store_false")
    args = parser.parse_args()

    wiki_root = Path(args.wiki_root).resolve()
    wiki_dir = wiki_root / "wiki"
    print(f"[fast-fixup] wiki_root={wiki_root} mode={'DRY' if args.dry_run else 'APPLY'}")

    scanned = updated = 0
    total_tags = total_rels = 0
    errors = []

    for md in sorted(wiki_dir.rglob("*.md")):
        if md.name in ("index.md", "log.md"):
            continue
        scanned += 1
        try:
            n_tags, n_rels = migrate_file(md, args.dry_run)
            if n_tags:
                updated += 1
                total_tags += n_tags
                total_rels += n_rels
        except Exception as e:
            errors.append((md, str(e)))

    print(f"[fast-fixup] scanned={scanned}")
    print(f"[fast-fixup] {'would_update' if args.dry_run else 'updated'}_pages={updated}")
    print(f"[fast-fixup] {'would_migrate' if args.dry_run else 'migrated'}_tags={total_tags}")
    print(f"[fast-fixup] {'would_add' if args.dry_run else 'added'}_relations={total_rels}")
    if errors:
        print(f"[fast-fixup] errors={len(errors)}")
        for p, e in errors[:5]:
            print(f"  {p}: {e}")


if __name__ == "__main__":
    main()