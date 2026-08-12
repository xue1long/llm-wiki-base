"""Heat decay CLI — 7 subcommands."""
import argparse
import shutil
import sys

from ..services.wiki_analysis import get_heat_tracker, get_zombie_detector
from ..wiki.storage.page_writer import read_page, write_page, page_path_for
from ..wiki.core.types import PageType
from .project_resolve import resolve_cli_project


def _resolve_ctx(project_arg):
    """Resolve project context; returns (ctx, WikiPaths).

    Thin wrapper over resolve_project that converts ProjectNotFoundError to
    a CLI-friendly stderr message + sys.exit(2).
    """
    return resolve_cli_project(project_arg)


def _infer_type(paths, slug):
    for t, dp in [(PageType.ENTITY, "wiki_entities"), (PageType.CONCEPT, "wiki_concepts"),
                  (PageType.SOURCE, "wiki_sources"), (PageType.SYNTHESIS, "wiki_synthesis")]:
        if (getattr(paths, dp) / f"{slug}.md").exists():
            return t
    return PageType.SOURCE


def _all_pages(paths):
    out = []
    for t, dp in [(PageType.SOURCE, "wiki_sources"), (PageType.ENTITY, "wiki_entities"),
                  (PageType.CONCEPT, "wiki_concepts"), (PageType.SYNTHESIS, "wiki_synthesis")]:
        for f in getattr(paths, dp).glob("*.md"):
            out.append(read_page(f))
    return out


def cmd_heat_show(args: argparse.Namespace) -> None:
    ctx, paths = _resolve_ctx(args.project)
    page_file = page_path_for(paths, _infer_type(paths, args.page_id), args.page_id)
    if not page_file.exists():
        print(f"Page not found: {args.page_id}", file=sys.stderr)
        sys.exit(2)
    p = read_page(page_file)
    print(f"  heat: {p.heat}")
    print(f"  last_used_at: {p.last_used_at}")
    print(f"  zombie_since: {p.zombie_since}")


def cmd_heat_top(args: argparse.Namespace) -> None:
    ctx, paths = _resolve_ctx(args.project)
    pages = _all_pages(paths)
    pages.sort(key=lambda p: -p.heat)
    for p in pages[:args.limit]:
        print(f"  {p.heat:3d}  {p.id}  ({p.type.value})")


def cmd_heat_cold(args: argparse.Namespace) -> None:
    ctx, paths = _resolve_ctx(args.project)
    pages = [p for p in _all_pages(paths) if p.heat < 30]
    for p in pages[:args.limit]:
        print(f"  {p.heat:3d}  {p.id}")


def cmd_heat_decay(args: argparse.Namespace) -> None:
    ctx, paths = _resolve_ctx(args.project)
    tracker = get_heat_tracker(paths)
    if args.dry_run:
        print("(dry run; no writes)")
        return
    events = tracker.decay()
    print(f"Applied {len(events)} decay events")


def cmd_heat_zombies(args: argparse.Namespace) -> None:
    ctx, paths = _resolve_ctx(args.project)
    zombies = get_zombie_detector().list_zombies(paths)
    for z in zombies:
        print(f"  {z['id']}  (zombie since {z['zombie_since']})")


def cmd_heat_restore(args: argparse.Namespace) -> None:
    """Reset heat to 100, set is_immutable=true."""
    ctx, paths = _resolve_ctx(args.project)
    page_file = page_path_for(paths, _infer_type(paths, args.page_id), args.page_id)
    if not page_file.exists():
        print(f"Page not found: {args.page_id}", file=sys.stderr)
        sys.exit(2)
    p = read_page(page_file)
    p.heat = 100
    p.is_immutable = True
    p.zombie_since = None
    write_page(paths, p)
    print(f"Restored {p.id}")


def cmd_heat_archive(args: argparse.Namespace) -> None:
    """Move zombie to wiki/_archive/."""
    ctx, paths = _resolve_ctx(args.project)
    page_file = page_path_for(paths, _infer_type(paths, args.page_id), args.page_id)
    if not page_file.exists():
        print(f"Page not found: {args.page_id}", file=sys.stderr)
        sys.exit(2)
    archive_dir = paths.wiki / "_archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(page_file), str(archive_dir / page_file.name))
    print(f"Archived {args.page_id}")
