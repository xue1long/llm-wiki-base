"""Wiki field/tag validation CLI."""
import argparse
import sys
from pathlib import Path

import yaml

from ..wiki.core.id_generator import is_valid_id
from ..wiki.storage.page_writer import read_page
from ..wiki.features.tag_namespace import validate_tags
from ..lib.project import resolve_project


def _resolve_ctx(project_arg):
    """Resolve project context; returns (ctx, WikiPaths) for compatibility.

    Delegates to the centralised helper; preserves the (ctx, paths) tuple
    interface for the two cmd_* callers.
    """
    return resolve_project(project_arg)


def cmd_fields_validate(args: argparse.Namespace) -> None:
    """Validate frontmatter of one page (L0-L3)."""
    _ctx, paths = _resolve_ctx(args.project)
    page_path = Path(args.path)
    if not page_path.is_absolute():
        page_path = paths.root / page_path
    if not page_path.exists():
        print(f"Page not found: {page_path}", file=sys.stderr)
        sys.exit(2)

    page = read_page(page_path)
    errors = []
    warnings = []
    # L0: id, title, type, sources
    if not page.id:
        errors.append("L0: missing id")
    if not page.title.strip():
        errors.append("L0: missing title")
    if not page.sources:
        errors.append("L0: missing sources")
    # L1 (v2.2): grade, processing_depth
    if page.grade not in ("A", "B", "C"):
        errors.append(f"L1: invalid grade: {page.grade}")
    _VALID_DEPTHS = {"memory", "concept", "source", "entity", "synthesis", "stub"}
    if page.processing_depth not in _VALID_DEPTHS:
        errors.append(f"L1: invalid processing_depth: {page.processing_depth}")
    # L4: id format (backwards-compat warning, non-fatal)
    if page.id and not is_valid_id(page.id):
        warnings.append(f"WARN: id '{page.id}' does not match UUID v7 or legacy slug format (backwards compat)")

    for w in warnings:
        print(f"  {w}")
    if errors:
        for e in errors:
            print(f"  {e}")
        print("FAIL")
        sys.exit(1)
    print("OK")


def _read_tags_from_frontmatter(page_path: Path) -> list[str]:
    """Read tags list from raw frontmatter (WikiPage doesn't have a tags field)."""
    if not page_path.exists():
        return []
    text = page_path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return []
    end = text.find("\n---", 4)
    if end < 0:
        return []
    fm_text = text[4:end]
    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError:
        return []
    tags = fm.get("tags", [])
    if not isinstance(tags, list):
        return []
    return [str(t) for t in tags]


def cmd_tags_validate(args: argparse.Namespace) -> None:
    """Validate tags of one page (or all pages if --all)."""
    _ctx, paths = _resolve_ctx(args.project)
    page_paths: list[Path] = []
    if args.all:
        for sub in [paths.wiki_sources, paths.wiki_entities, paths.wiki_concepts, paths.wiki_synthesis]:
            for f in sub.glob("*.md"):
                page_paths.append(f)
    else:
        if not args.page_path:
            print("Error: provide page_path or use --all", file=sys.stderr)
            sys.exit(2)
        page_path = Path(args.page_path)
        if not page_path.is_absolute():
            page_path = paths.root / page_path
        page_paths.append(page_path)

    all_invalid: list[tuple[str, list[str]]] = []
    for pp in page_paths:
        try:
            page = read_page(pp)
        except Exception:
            page = None
        page_id = page.id if page else pp.stem
        tags = _read_tags_from_frontmatter(pp)
        invalid = validate_tags(tags)
        if invalid:
            all_invalid.append((page_id, invalid))
    if all_invalid:
        for pid, inv in all_invalid:
            print(f"  {pid}: {inv}")
        sys.exit(1)
    print("OK")
