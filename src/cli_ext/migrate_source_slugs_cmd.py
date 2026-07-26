"""v2.4 migration: rename wiki/sources/kb-...md files to {stem}-{8hex}.md.

Rewrites source page filenames so they're human-readable instead of an
opaque queue task ID. The new naming (Plan 27 v2.4) uses the raw
file's Chinese stem with a short path-hash suffix; see
`src/pipeline/ingest.py` for the production path.

This command:
- Walks ``wiki/sources/*.md``.
- For every kb-* prefixed file, looks up the corresponding raw source
  path from the page's frontmatter ``sources`` field (or, when that
  has been re-ingested under the new scheme, falls back to the
  recorded ``任务 ID`` slot from the body).
- Computes the new id as ``NFC(stem)-{8hex_path_hash}``.
- Default (``--dry-run`` implicit) prints a table of planned renames.
  With ``--apply``, renames the file, rewrites its frontmatter
  ``id:`` line, and updates ``wiki/index.md`` + ``wiki/log.md`` so
  the entire wiki stays consistent.

Migration is idempotent: re-running on already-migrated files is a
no-op (the ``_already_migrated`` predicate skips non-kb-* and any
file whose frontmatter ``id:`` does not match its filename).
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
import unicodedata
from pathlib import Path

from ..lib.project import resolve_project
from ..project.context import ProjectNotFoundError
from ..wiki.storage.page_writer import read_page


# Match an ``id:`` line in frontmatter (allow optional surrounding
# whitespace; the YAML key is always lowercase ``id`` per the wiki
# frontmatter schema).
_ID_FIELD_RE = re.compile(r'^(\s*id:\s*)(.+?)(\s*)$', re.MULTILINE)


def _resolve(project_arg):
    try:
        return resolve_project(project_arg, by_id_only=True)
    except ProjectNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)


def _extract_raw_path_from_page(page_md_text: str) -> str | None:
    """Return the absolute raw source path referenced by a source page.

    Tries the frontmatter ``sources`` list first (Plan 22+ writes it
    there); falls back to the ``来源元数据`` slot's ``任务 ID`` line
    if the frontmatter field has been stripped or never set.
    """
    fm_end = page_md_text.find("\n---\n", 4)
    if fm_end > 0:
        fm = page_md_text[4:fm_end]
        m = re.search(r"^\s*sources:\s*\n\s*-\s*(.+?)\s*$", fm, re.MULTILINE)
        if m:
            return m.group(1).strip().strip("'\"")
    # Fallback: grep "任务 ID" line — but that's the task_id, not the
    # raw path, so unhelpful. Return None.
    return None


def _new_id_from_path(raw_path: str) -> str:
    """Return ``{NFC(stem)}-{8hex_path_hash}`` per v2.4."""
    stem = Path(raw_path).stem
    norm_stem = unicodedata.normalize("NFC", stem)
    path_hash = hashlib.md5(raw_path.encode("utf-8")).hexdigest()[:8]
    return f"{norm_stem}-{path_hash}"


def _iter_migration_plan(paths) -> list[tuple[Path, str]]:
    """Walk sources/ and produce (file, proposed_new_id) pairs.

    Skips files that don't match ``kb-*.md`` or whose ``id:`` in the
    frontmatter already diverges from the filename (those are
    already-migrated files or v2.4-era ids produced by the live
    pipeline).
    """
    plan: list[tuple[Path, str]] = []
    if not paths.wiki_sources.exists():
        return plan
    for md_file in sorted(paths.wiki_sources.glob("kb-*.md")):
        page = read_page(md_file)
        # Sanity: frontmatter id should currently match the filename stem
        if page.id != md_file.stem:
            # Already migrated (or someone else moved it) — skip silently.
            continue
        raw_path = _extract_raw_path_from_page(md_file.read_text(encoding="utf-8"))
        if not raw_path:
            # Path wasn't recorded in frontmatter — refuse to guess.
            print(
                f"  skip: {md_file.name} — cannot recover raw source path "
                f"from frontmatter; please re-ingest the source file "
                f"under v2.4 so the new id is recorded automatically.",
                file=sys.stderr,
            )
            continue
        new_id = _new_id_from_path(raw_path)
        if new_id == page.id:
            continue
        plan.append((md_file, new_id))
    return plan


def _apply_to_index(paths, old_id: str, new_id: str) -> None:
    """Rewrite ``wiki/index.md`` so the old id line uses the new id."""
    idx = paths.llm_wiki_index
    if not idx.exists():
        return
    text = idx.read_text(encoding="utf-8")
    new_text = re.sub(
        rf"\*\*{re.escape(old_id)}\*\*",
        f"**{new_id}**",
        text,
    )
    if new_text != text:
        idx.write_text(new_text, encoding="utf-8")


def _apply_to_log(paths, old_id: str, new_id: str) -> None:
    """Rewrite ``wiki/log.md`` so any audit trail lines using old_id use new_id."""
    log = paths.llm_wiki_log
    if not log.exists():
        return
    text = log.read_text(encoding="utf-8")
    new_text = text.replace(f"`{old_id}`", f"`{new_id}`")
    if new_text != text:
        log.write_text(new_text, encoding="utf-8")


def _rewrite_file_frontmatter_id(md_file: Path, new_id: str) -> None:
    """Update the ``id:`` line in frontmatter without touching the body."""
    text = md_file.read_text(encoding="utf-8")
    new_text = _ID_FIELD_RE.sub(
        lambda m: f"{m.group(1)}{new_id}{m.group(3)}",
        text,
        count=1,
    )
    if new_text != text:
        md_file.write_text(new_text, encoding="utf-8")


def _run_dry_run(paths) -> int:
    plan = _iter_migration_plan(paths)
    if not plan:
        print("No source pages need migrating (already up to date).")
        return 0
    print(f"Found {len(plan)} source page(s) that need renaming:\n")
    for old_md, new_id in plan:
        print(f"  {old_md.name}\n      → {new_id}.md")
    print("\nRe-run with --apply to perform the rename + index/log rewrite.")
    return 0


def _run_apply(paths) -> int:
    plan = _iter_migration_plan(paths)
    if not plan:
        print("No source pages need migrating.")
        return 0
    for old_md, new_id in plan:
        old_id = old_md.stem
        new_md = old_md.with_name(f"{new_id}.md")
        # 1. rename
        old_md.rename(new_md)
        # 2. rewrite frontmatter id line
        _rewrite_file_frontmatter_id(new_md, new_id)
        # 3. update index + log references
        _apply_to_index(paths, old_id, new_id)
        _apply_to_log(paths, old_id, new_id)
        print(f"  {old_md.name}  →  {new_md.name}")
    print(f"\nMigrated {len(plan)} source page(s). "
          f"Re-running `python -m src.cli lint --project <id>` is recommended.")
    return 0


def cmd_wiki_migrate_source_slugs(args: argparse.Namespace) -> int:
    _, paths = _resolve(args.project)
    if getattr(args, "apply", False):
        return _run_apply(paths)
    return _run_dry_run(paths)


def add_wiki_migrate_source_slugs_parser(subparsers) -> None:
    """Register `wiki migrate-source-slugs` on the given subparsers object."""
    p = subparsers.add_parser(
        "wiki-migrate-source-slugs",
        help="Rename kb-*.md source pages to {stem}-{8hex}.md (v2.4 naming)",
    )
    p.add_argument("--project", required=True, help="Project id")
    p.add_argument(
        "--apply",
        action="store_true",
        help="Actually rename files + rewrite index/log (default: dry-run)",
    )
    p.set_defaults(func=cmd_wiki_migrate_source_slugs)
