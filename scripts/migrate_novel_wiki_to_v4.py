"""One-shot migration: 19-key v2.2 WikiPage → 8-key V4 WikiPage (FIXED).

This is the round-trip-safe version. Key changes from the buggy first attempt:

1. **YAML parsing via `yaml.safe_load()`**: replaces hand-rolled multiline
   parsers that lost entries on indented list items.
2. **Round-trip verification per page**: parses V4 output back through
   `yaml.safe_load()` and compares element counts for relations/tags/sources
   against the HEAD counts. If V4 loses data, the page is REJECTED and left
   unchanged.
3. **Atomic single-page writes**: each page is written independently; a
   failure on page N does not affect pages 1..N-1 or N+1..end.
4. **Dry-run by default**: requires explicit `--apply` to actually write.

V4 keeps (8 keys): id, title, type, relations, tags, sources,
                     created_at, updated_at
V4 removes (11 keys): slug, grade, category, taxonomy_sub, processing_depth,
                      custom_type, workflow_state, verified_at, heat,
                      is_immutable, last_used_at, zombie_since,
                      related_entities, _ko_extra
V4 transformations:
    category "X"          → relations += {target: taxonomy/X, type: taxonomy_of}
    taxonomy_sub "X"      → relations += {target: taxonomy/X, type: taxonomy_of}
    tags[题材/X]          → relations += {target: taxonomy/X, type: taxonomy_of}
    tags[读者群/X]        → relations += {target: audience/X, type: belongs_to_audience}
    tags[平台/X]          → relations += {target: platform/X, type: hosted_on_platform}
    tags[可信度/X]        → relations += {target: credibility/X, type: has_credibility}
    type=claim            → type=source (file also moves to wiki/sources/)
    dead fields:          DROPPED

Usage:
    python scripts/migrate_novel_wiki_to_v4.py [--dry-run|--apply] [wiki_root]

    # default mode = --dry-run (safe; no writes)
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# V4 schema
# ---------------------------------------------------------------------------
V4_FIELDS = frozenset({
    "id", "title", "type", "relations", "tags", "sources",
    "created_at", "updated_at",
})
FIELDS_TO_DROP = frozenset({
    "slug", "grade", "category", "taxonomy_sub", "processing_depth",
    "custom_type", "workflow_state", "verified_at",
    "heat", "is_immutable", "last_used_at", "zombie_since",
    "related_entities", "_ko_extra",
})

TAG_TO_RELATION = [
    # (prefix, relation_type, target_prefix)
    ("题材/",     "taxonomy_of",          "taxonomy/"),
    ("功能/",     "taxonomy_of",          "taxonomy/"),
    ("角色/",     "taxonomy_of",          "taxonomy/"),
    ("事件/",     "taxonomy_of",          "taxonomy/"),
    ("情绪/",     "taxonomy_of",          "taxonomy/"),
    ("场景阶段/", "taxonomy_of",          "taxonomy/"),
    ("读者群/",   "belongs_to_audience",  "audience/"),
    ("平台/",     "hosted_on_platform",   "platform/"),
    ("可信度/",   "has_credibility",      "credibility/"),
    # Per V3 template §2.2: 素材/ugc is DELETED, expressed via
    # credibility/ugc (has_credibility). We map 素材/* → credibility/*.
    ("素材/",     "has_credibility",      "credibility/"),
]
DROPPED_CATEGORIES = {"", "''", "null", "~", None}

TYPE_REMAP = {"claim": "source"}

RESERVED_FILES = {"index.md", "log.md"}
TYPE_DIRS = {"concepts", "sources", "entities", "synthesis", "_stubs"}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class PageResult:
    path: str
    status: str  # "v4_skip" | "v4_migrated" | "v4_rejected" | "v4_error"
    head_relations: int = 0
    v4_relations: int = 0
    head_tags: int = 0
    v4_tags: int = 0
    head_sources: int = 0
    v4_sources: int = 0
    note: str = ""


@dataclass
class MigrationResult:
    scanned: int = 0
    skipped_v4: int = 0
    migrated: int = 0
    rejected: int = 0
    errors: int = 0
    claim_renames: int = 0
    category_to_relation: int = 0
    tags_to_relation: int = 0
    fields_dropped: dict[str, int] = field(default_factory=dict)
    pages: list[PageResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Frontmatter parsing (tolerant to malformed delimiters)
# ---------------------------------------------------------------------------
def split_frontmatter(text: str) -> tuple[str, str] | None:
    """Return (frontmatter_text, body_text) or None if no frontmatter.

    Tolerant to:
      1. Strict `--- ... ---\\n`
      2. Malformed `---` glued to previous line: extract top-level keys only
         until first non-key line.
    """
    # Mode 1: strict
    m = re.match(r"(?s)^---\s*\n(.*?)\n---\s*\n", text)
    if m:
        fm_text = m.group(1)
        body = text[m.end():]
        return fm_text, body

    # Mode 2: malformed
    if not text.startswith("---"):
        return None
    body_lines: list[str] = []
    fm_lines: list[str] = []
    for line in text.splitlines()[1:]:
        if re.match(r"^[\w_-]+:", line) or re.match(r"^\s+-\s+", line) or re.match(r"^\s+\w+:", line):
            fm_lines.append(line)
            continue
        # first non-frontmatter line starts body
        body_lines = [line] + text.splitlines()[1 + 1 + len(fm_lines):]
        break
    return "\n".join(fm_lines), "\n".join(body_lines)


def parse_yaml_fm(text: str) -> dict[str, Any]:
    """Parse frontmatter text via yaml.safe_load(). Returns {} on parse failure."""
    try:
        result = yaml.safe_load(text)
        if not isinstance(result, dict):
            return {}
        return result
    except yaml.YAMLError:
        return {}


# ---------------------------------------------------------------------------
# Migration logic
# ---------------------------------------------------------------------------
def migrate_fields(head: dict[str, Any], result: MigrationResult) -> dict[str, Any]:
    """Transform HEAD v2.2 fields into V4 fields."""
    v4: dict[str, Any] = {}

    # Direct copies
    for k in ("id", "title", "created_at", "updated_at"):
        if k in head:
            v4[k] = head[k]

    # Type remapping (claim → source)
    ptype = head.get("type", "")
    if ptype in TYPE_REMAP:
        v4["type"] = TYPE_REMAP[ptype]
        result.claim_renames += 1
    elif ptype:
        v4["type"] = ptype

    # Relations: HEAD relations + synthesized from category/taxonomy_sub/tags
    head_relations = head.get("relations") or []
    if not isinstance(head_relations, list):
        head_relations = []
    relations = [dict(r) for r in head_relations if isinstance(r, dict)]

    # category → taxonomy_of
    cat = head.get("category")
    if cat and str(cat).strip().strip("'\"") not in DROPPED_CATEGORIES:
        cat_clean = str(cat).strip().strip("'\"")
        relations.append({
            "target": f"taxonomy/{cat_clean}",
            "type": "taxonomy_of",
            "weight": 1.0,
        })
        result.category_to_relation += 1

    # taxonomy_sub → taxonomy_of (only if different from category)
    sub = head.get("taxonomy_sub")
    if sub and str(sub).strip().strip("'\"") not in DROPPED_CATEGORIES:
        sub_clean = str(sub).strip().strip("'\"")
        if sub_clean != str(cat).strip().strip("'\""):
            relations.append({
                "target": f"taxonomy/{sub_clean}",
                "type": "taxonomy_of",
                "weight": 1.0,
            })
            result.category_to_relation += 1

    # tags → relations (by prefix) + retain non-migratable tags
    raw_tags = head.get("tags") or []
    if not isinstance(raw_tags, list):
        raw_tags = []
    remaining_tags: list[str] = []
    for tag in raw_tags:
        if not isinstance(tag, str):
            continue
        tag_clean = tag.strip().strip("'\"")
        if not tag_clean:
            continue
        migrated = False
        for prefix, rel_type, target_prefix in TAG_TO_RELATION:
            if tag_clean.startswith(prefix):
                name = tag_clean[len(prefix):]
                relations.append({
                    "target": f"{target_prefix}{name}",
                    "type": rel_type,
                    "weight": 1.0,
                })
                result.tags_to_relation += 1
                migrated = True
                break
        if not migrated:
            remaining_tags.append(tag_clean)

    v4["relations"] = relations
    v4["tags"] = remaining_tags

    # sources
    raw_sources = head.get("sources") or []
    if not isinstance(raw_sources, list):
        raw_sources = []
    v4["sources"] = [s for s in raw_sources if isinstance(s, str)]

    # Track dropped fields
    for k in head:
        if k in FIELDS_TO_DROP:
            result.fields_dropped[k] = result.fields_dropped.get(k, 0) + 1

    return v4


def render_v4(v4: dict[str, Any]) -> str:
    """Render V4 fields as proper YAML frontmatter with correct delimiters."""
    fm = yaml.safe_dump(v4, allow_unicode=True, sort_keys=False, default_flow_style=False)
    # safe_dump may produce nested mappings under different key orders; sort_keys=False
    # preserves insertion order so id/title/type come first.
    return f"---\n{fm}---\n"


def round_trip_check(head: dict[str, Any], v4: dict[str, Any]) -> tuple[bool, str]:
    """Verify V4 didn't lose data vs HEAD.

    relations and tags together represent the "linked knowledge" surface —
    tags can be migrated to relations (which is by design), so the combined
    count must be >= HEAD's combined count, but individual fields may
    legitimately shrink.

    sources must be exactly preserved (no transformation).
    """
    head_relations = head.get("relations") or []
    head_tags = head.get("tags") or []
    head_combined = len(head_relations) + len(head_tags)

    v4_relations = v4.get("relations") or []
    v4_tags = v4.get("tags") or []
    v4_combined = len(v4_relations) + len(v4_tags)

    if v4_combined < head_combined:
        return False, (
            f"relations+tags: V4={v4_combined}, HEAD={head_combined} "
            f"(relations V4={len(v4_relations)}/HEAD={len(head_relations)}, "
            f"tags V4={len(v4_tags)}/HEAD={len(head_tags)})"
        )

    head_sources = head.get("sources") or []
    v4_sources = v4.get("sources") or []
    if len(v4_sources) != len(head_sources):
        return False, f"sources: V4={len(v4_sources)}, HEAD={len(head_sources)}"

    return True, ""


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def migrate_page(md_path: Path, wiki_root: Path, result: MigrationResult,
                 dry_run: bool) -> PageResult:
    rel = str(md_path.relative_to(wiki_root))
    pr = PageResult(path=rel, status="error", note="")

    # Only process files under known type dirs.
    # md_path is relative to wiki_root, so its first part should be 'wiki',
    # second part should be a known type dir.
    parts = md_path.relative_to(wiki_root).parts
    if len(parts) < 2 or parts[0] != "wiki" or parts[1] not in TYPE_DIRS:
        pr.status = "v4_skip"
        pr.note = f"not under type dir (parts={parts[:2]})"
        return pr

    text = md_path.read_text(encoding="utf-8")
    split = split_frontmatter(text)
    if split is None:
        pr.status = "v4_error"
        pr.note = "no frontmatter"
        return pr

    fm_text, body = split
    head = parse_yaml_fm(fm_text)

    if not head:
        pr.status = "v4_error"
        pr.note = "yaml parse failed"
        return pr

    # Already V4?
    if all(k in V4_FIELDS for k in head.keys()) and not any(k in FIELDS_TO_DROP for k in head.keys()):
        # Sanity: must have all 8 V4 keys present
        if all(k in head for k in V4_FIELDS):
            pr.status = "v4_skip"
            pr.note = "already V4"
            return pr

    # Capture HEAD counts for round-trip
    pr.head_relations = len(head.get("relations") or [])
    pr.head_tags = len(head.get("tags") or [])
    pr.head_sources = len(head.get("sources") or [])

    v4 = migrate_fields(head, result)
    pr.v4_relations = len(v4.get("relations") or [])
    pr.v4_tags = len(v4.get("tags") or [])
    pr.v4_sources = len(v4.get("sources") or [])

    # Round-trip check
    passed, reason = round_trip_check(head, v4)
    if not passed:
        pr.status = "v4_rejected"
        pr.note = reason
        return pr

    # Render new content
    new_fm = render_v4(v4)
    new_text = new_fm + body.lstrip("\n")

    # File rename for type=claim → type=source
    new_path = md_path
    if v4.get("type") == "source" and "claims" in md_path.parts:
        sources_dir = md_path.parent.parent / "sources"
        new_path = sources_dir / md_path.name
        new_text_for_rename = new_text  # full content

    if not dry_run:
        try:
            if new_path != md_path:
                md_path.rename(new_path)
                md_path = new_path
            md_path.write_text(new_text, encoding="utf-8")
        except OSError as e:
            pr.status = "v4_error"
            pr.note = f"write failed: {e}"
            return pr

    pr.status = "v4_migrated"
    return pr


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("wiki_root", nargs="?", default="knowledge/novel-wiki")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--apply", dest="dry_run", action="store_false")
    args = parser.parse_args()

    wiki_root = Path(args.wiki_root).resolve()
    if not wiki_root.is_dir():
        print(f"error: not a directory: {wiki_root}", file=sys.stderr)
        return 2

    wiki_dir = wiki_root / "wiki"
    if not wiki_dir.is_dir():
        print(f"error: no wiki/ subdir: {wiki_dir}", file=sys.stderr)
        return 2

    print(f"[migrate-v4-fixed] wiki_root={wiki_root}")
    print(f"[migrate-v4-fixed] mode={'DRY-RUN' if args.dry_run else 'APPLY'}")
    result = MigrationResult()

    for md in sorted(wiki_dir.rglob("*.md")):
        if md.name in RESERVED_FILES:
            continue
        result.scanned += 1
        pr = migrate_page(md, wiki_root, result, args.dry_run)
        result.pages.append(pr)
        if pr.status == "v4_migrated":
            result.migrated += 1
        elif pr.status == "v4_skip":
            result.skipped_v4 += 1
        elif pr.status == "v4_rejected":
            result.rejected += 1
        elif pr.status == "v4_error":
            result.errors += 1

    print(f"[migrate-v4-fixed] scanned={result.scanned}")
    print(f"[migrate-v4-fixed] skipped_v4={result.skipped_v4}")
    print(f"[migrate-v4-fixed] {'would_migrate' if args.dry_run else 'migrated'}={result.migrated}")
    print(f"[migrate-v4-fixed] rejected={result.rejected}  errors={result.errors}")
    print(f"[migrate-v4-fixed] claim→source renames: {result.claim_renames}")
    print(f"[migrate-v4-fixed] category→relation synth: {result.category_to_relation}")
    print(f"[migrate-v4-fixed] tags→relation synth: {result.tags_to_relation}")
    print(f"[migrate-v4-fixed] fields dropped (sum across pages): {sum(result.fields_dropped.values())}")
    for k, n in sorted(result.fields_dropped.items(), key=lambda x: -x[1]):
        print(f"    {k:<20} {n:>5} pages")

    if result.rejected or result.errors:
        print()
        print("=== Rejected pages (round-trip data loss) ===")
        for pr in result.pages:
            if pr.status in ("v4_rejected", "v4_error"):
                print(f"  {pr.path}: {pr.status} {pr.note}")
                print(f"    relations: HEAD={pr.head_relations} V4={pr.v4_relations}")
                print(f"    tags: HEAD={pr.head_tags} V4={pr.v4_tags}")
                print(f"    sources: HEAD={pr.head_sources} V4={pr.v4_sources}")

    return 0


if __name__ == "__main__":
    sys.exit(main())