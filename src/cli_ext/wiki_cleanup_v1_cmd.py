"""Strict-scope cleanup for the ruflo-kb wiki.

Three subcommands, none of them destructive without explicit opt-in:

- ``archive-state``: snapshots current wiki/{sources,entities,concepts,
  synthesis,index.md,log.md} to ``wiki/_archive/pre-cleanup-{TS}/``.
- ``rebuild-from-raws``: wipes wiki/ type-dirs, re-ingests every raw
  via the live ingest pipeline, computes deletion candidates
  (archive files whose slug was NOT reproduced), and refuses to
  delete anything without an explicit ``--delete <path>``.
- ``restore-from-archive``: emergency brake. Moves an archived
  snapshot back under wiki/, never touching raw/.

Invariants:

- **raw/ untouched**: source files are never read, moved, modified,
  or deleted by any subcommand.
- **Archive append-only**: ``wiki/_archive/<snapshot>/`` is created
  once per invocation and never overwritten.
- **Per-file delete**: ``rebuild-from-raws --delete <path>`` is the
  ONLY destructive path; it accepts exactly one path, refuses raw
  files and paths outside ``wiki/``.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import shutil
import sys
from datetime import datetime
from pathlib import Path

from ..lib.project import resolve_project
from ..project.context import ProjectNotFoundError


# Files we consider "wiki content" — everything we know how to reset.
_WIKI_TYPED_DIRS = ("sources", "entities", "concepts", "synthesis")
_WIKI_TOP_LEVEL_FILES = ("index.md", "log.md")


def _resolve(project_arg):
    try:
        return resolve_project(project_arg, by_id_only=True)
    except ProjectNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)


def _list_wiki_files(wiki_root: Path) -> list[Path]:
    """All files in wiki/ that belong to wiki content (not raw/, not _archive)."""
    out: list[Path] = []
    if not wiki_root.exists():
        return out
    for d in _WIKI_TYPED_DIRS:
        sub = wiki_root / d
        if sub.exists():
            for f in sorted(sub.glob("*.md")):
                out.append(f)
    for name in _WIKI_TOP_LEVEL_FILES:
        f = wiki_root / name
        if f.exists():
            out.append(f)
    return out


# ---------------------------------------------------------------------------
# archive-state
# ---------------------------------------------------------------------------


def _atomic_snapshot(wiki_root: Path, dst: Path) -> tuple[int, list[tuple[Path, Path]]]:
    """Move every wiki-content file to dst/. ABORT + roll back on first failure.

    Implementation note: ``shutil.move(str(src), str(target))`` is
    repeated per-file. If any move raises ``OSError`` we attempt
    best-effort rollback of every already-moved pair in reverse
    order, then ``raise SystemExit(3)``. Raw + archive dirs are
    untouched.
    """
    n_moved = 0
    moved_pairs: list[tuple[Path, Path]] = []

    # Pre-create the per-type subdirs so moves into nested targets succeed.
    for d in _WIKI_TYPED_DIRS:
        (dst / d).mkdir(parents=True, exist_ok=True)

    for src in _list_wiki_files(wiki_root):
        if dst in src.parents:
            # Defensive: an archive shouldn't be re-archived into itself.
            continue
        rel = src.relative_to(wiki_root)
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(src), str(target))
        except OSError as e:
            print(f"ABORT: failed to move {src} -> {target}: {e}",
                  file=sys.stderr)
            for moved_src, moved_dst in reversed(moved_pairs):
                try:
                    shutil.move(str(moved_dst), str(moved_src))
                except OSError as rb_err:
                    print(
                        f"warning: rollback failed {moved_dst} -> "
                        f"{moved_src}: {rb_err}",
                        file=sys.stderr,
                    )
            raise SystemExit(3)
        moved_pairs.append((src, target))
        n_moved += 1
    return n_moved, moved_pairs


def cmd_wiki_archive_state(args: argparse.Namespace) -> int:
    """Move current wiki content to ``wiki/_archive/pre-cleanup-{TS}/``."""
    _, paths = _resolve(args.project)
    wiki_root = paths.wiki
    archive_root = wiki_root / "_archive"
    archive_root.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = archive_root / f"pre-cleanup-{stamp}"
    if dst.exists():
        print(f"Error: archive {dst} already exists; refusing to overwrite.",
              file=sys.stderr)
        return 4
    dst.mkdir(parents=False)
    print(f"Snapshotting to {dst} ...")
    n_moved, moved_pairs = _atomic_snapshot(wiki_root, dst)
    print(f"Moved {n_moved} file(s) to {dst}")
    for src, target in moved_pairs:
        rel_src = src.relative_to(paths.root)
        rel_target = target.relative_to(paths.root)
        print(f"  {rel_src}  ->  {rel_target}")
    print()
    print("To restore:")
    print(f"  python -m src.cli wiki-cleanup-v1-data restore-from-archive "
          f"--project {args.project} --archive {dst.relative_to(paths.root)}")
    return 0


# ---------------------------------------------------------------------------
# rebuild-from-raws
# ---------------------------------------------------------------------------


def _existing_archive(wiki_root: Path) -> Path | None:
    """Return the most recent archive dir, or None."""
    archive_root = wiki_root / "_archive"
    if not archive_root.exists():
        return None
    snaps = sorted(
        [p for p in archive_root.iterdir() if p.is_dir()
         and p.name.startswith("pre-cleanup-")],
        key=lambda p: p.name,
        reverse=True,
    )
    return snaps[0] if snaps else None


def _list_files_under(root: Path) -> dict[str, Path]:
    """``{relative path string: absolute Path}`` for every .md under root."""
    out: dict[str, Path] = {}
    if not root.exists():
        return out
    for p in sorted(root.rglob("*.md")):
        rel = p.relative_to(root)
        out[str(rel).replace("\\", "/")] = p
    return out


def _list_raws(paths) -> list[Path]:
    raw_dir = paths.raw_sources
    if not raw_dir.exists():
        return []
    return sorted(p for p in raw_dir.glob("*.md") if p.is_file())


def _run_reingest(paths, raws: list[Path]) -> dict[str, int]:
    """Re-ingest each raw via run_ingest(). Returns ``{raw_name: pages}``."""
    from ..pipeline.pipeline import run_ingest
    from ..llm.registry import ProviderRegistry
    from ..llm.provider_factory import create_llm_provider

    config = ProviderRegistry.get_default()
    provider = create_llm_provider(config.name)

    out: dict[str, int] = {}
    for raw in raws:
        text = raw.read_text(encoding="utf-8")
        task_id = f"cleanup-{hashlib.md5(str(raw).encode()).hexdigest()[:8]}"
        try:
            pages = asyncio.run(run_ingest(
                paths=paths,
                source_path=raw,
                source_text=text,
                provider=provider,
                task_id=task_id,
            ))
            out[raw.name] = len(pages)
            print(f"  re-ingested {raw.name}: {len(pages)} page(s)")
        except Exception as e:
            print(f"  FAILED: {raw.name}: {e}", file=sys.stderr)
            out[raw.name] = -1
    return out


def _rebuild_state(paths) -> tuple[list[Path], dict[str, int]]:
    raws = _list_raws(paths)
    if not raws:
        print("No raw files; nothing to re-ingest.", file=sys.stderr)
        return [], {}
    for d in _WIKI_TYPED_DIRS:
        sub = paths.wiki / d
        if sub.exists():
            shutil.rmtree(sub)
        sub.mkdir(parents=True, exist_ok=True)
    counts = _run_reingest(paths, raws)
    return raws, counts


def _print_manifest(raws: list[Path], counts: dict[str, int],
                    archive: Path | None,
                    deletion_candidates: list[Path]) -> None:
    print()
    print("=== Rebuild manifest ===")
    print(f"Archive reference: {archive if archive else '(none)'}")
    print(f"Re-ingested {len(raws)} raw file(s):")
    for raw in raws:
        c = counts.get(raw.name, -1)
        flag = "OK" if c >= 0 else "FAIL"
        print(f"  [{flag}] {raw.name}  →  {c} downstream page(s)")
    print()
    if deletion_candidates:
        print(f"Deletion candidates ({len(deletion_candidates)}):")
        print("(archive files whose slug was NOT reproduced by re-ingest)")
        print()
        for c in deletion_candidates:
            print(f"  --delete {c}")
    else:
        print("No deletion candidates — every archive file is also in the new state.")


def cmd_wiki_rebuild_from_raws(args: argparse.Namespace) -> int:
    """Wipe type-dirs, re-ingest raw, list deletion candidates."""
    _, paths = _resolve(args.project)
    wiki_root = paths.wiki
    archive = _existing_archive(wiki_root)

    # --delete path: per-file, explicit-opt-in only.
    if args.delete:
        target = Path(args.delete)
        if not target.is_absolute():
            target = (paths.root / args.delete).resolve()
        # Safety rail 1 (most specific): raw/ files. We check this first
        # so the more specific reason gets surfaced instead of a
        # generic "outside wiki tree".
        try:
            raw_sources_resolved = paths.raw_sources.resolve()
        except OSError:
            raw_sources_resolved = paths.raw_sources
        if target.is_relative_to(raw_sources_resolved):
            print(f"Error: refusing to delete a raw file: {target}",
                  file=sys.stderr)
            return 6
        # Safety rail 2: outside the wiki/ tree?
        try:
            wiki_root_resolved = wiki_root.resolve()
        except OSError:
            wiki_root_resolved = wiki_root
        if not str(target).startswith(str(wiki_root_resolved)):
            print(f"Error: refusing to delete outside wiki/ tree: {target}",
                  file=sys.stderr)
            return 5
        if not target.exists():
            print(f"Error: file no longer exists (already deleted?): {target}",
                  file=sys.stderr)
            return 7
        print(f"Deleting {target}")
        target.unlink()
        print("Done. Re-run lint to confirm a clean state.")
        return 0

    raw_files = _list_raws(paths)

    if args.apply:
        if not archive:
            print("Error: --apply requires an existing archive. "
                  "Run `wiki-cleanup-v1-data archive-state` first.",
                  file=sys.stderr)
            return 8
        raws, counts = _rebuild_state(paths)
        archive_files = _list_files_under(archive)
        current_files = _list_files_under(wiki_root)
        candidates = [archive_files[k] for k in archive_files if k not in current_files]
        _print_manifest(raws, counts, archive, candidates)
        return 0

    # Dry-run path: project candidate list without rebuilding.
    if archive:
        archive_files = _list_files_under(archive)
        current_files = _list_files_under(wiki_root)
        current_basenames = {p.name for p in current_files.values()}
        candidates = [p for rel, p in archive_files.items()
                      if p.name not in current_basenames]
    else:
        candidates = []

    print("=== Dry-run plan ===")
    print(f"Project: {args.project}")
    print(f"Archive reference: {archive if archive else '(none — run archive-state first)'}")
    print(f"raw files to re-ingest ({len(raw_files)}):")
    for raw in raw_files:
        print(f"  {raw.name}")
    print()
    print(f"(projection) deletion candidates ({len(candidates)}):")
    for c in candidates:
        print(f"  {c}")
    print()
    print("To execute the rebuild (requires prior archive-state):")
    print(f"  python -m src.cli wiki-cleanup-v1-data rebuild-from-raws "
          f"--project {args.project} --apply")
    return 0


# ---------------------------------------------------------------------------
# restore-from-archive
# ---------------------------------------------------------------------------


def cmd_wiki_restore_from_archive(args: argparse.Namespace) -> int:
    _, paths = _resolve(args.project)
    archive_root = paths.wiki / "_archive"
    snap_rel = args.archive
    snap = (paths.root / snap_rel).resolve() \
        if not Path(snap_rel).is_absolute() else Path(snap_rel).resolve()
    if not snap.is_relative_to(archive_root.resolve()):
        print(f"Error: archive path must be under {archive_root}: {snap}",
              file=sys.stderr)
        return 9
    if not snap.exists():
        print(f"Error: archive does not exist: {snap}", file=sys.stderr)
        return 10
    moved = 0
    try:
        for src in _list_files_under(snap):
            rel = src.relative_to(snap)
            dst = paths.wiki / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                print(f"  skip (collision): {dst}", file=sys.stderr)
                continue
            shutil.move(str(src), str(dst))
            moved += 1
    except OSError as e:
        print(f"Error during restore: {e}", file=sys.stderr)
        return 11
    print(f"Restored {moved} file(s) from {snap}")
    return 0


# ---------------------------------------------------------------------------
# Argument-parser registration
# ---------------------------------------------------------------------------


def add_wiki_cleanup_v1_parser(subparsers) -> None:
    """Register ``wiki-cleanup-v1-data <sub>`` style commands."""
    p = subparsers.add_parser(
        "wiki-cleanup-v1-data",
        help="Strict-scope cleanup: snapshot, rebuild, restore (Plan v2.5).",
    )
    sub = p.add_subparsers(dest="wiki_cleanup_command", required=True)

    p_arch = sub.add_parser(
        "archive-state",
        help="Move current wiki content to _archive/pre-cleanup-{TS}/.",
    )
    p_arch.add_argument("--project", required=True)
    p_arch.set_defaults(func=cmd_wiki_archive_state)

    p_rebuild = sub.add_parser(
        "rebuild-from-raws",
        help="Wipe type-dirs + re-ingest raw + list deletion candidates.",
    )
    p_rebuild.add_argument("--project", required=True)
    p_rebuild.add_argument(
        "--apply",
        action="store_true",
        help="Execute rebuild (requires prior archive-state).",
    )
    p_rebuild.add_argument(
        "--delete",
        metavar="PATH",
        help="Per-file delete: pass a path printed by --apply's manifest.",
    )
    p_rebuild.add_argument(
        "--candidates",
        action="store_true",
        help="(Reserved) List candidates only. Currently a no-op alias.",
    )
    p_rebuild.set_defaults(func=cmd_wiki_rebuild_from_raws)

    p_restore = sub.add_parser(
        "restore-from-archive",
        help="Move an archive back into wiki/. Single-shot emergency brake.",
    )
    p_restore.add_argument("--project", required=True)
    p_restore.add_argument(
        "--archive",
        required=True,
        help="Path to archive dir (relative to project root OK).",
    )
    p_restore.set_defaults(func=cmd_wiki_restore_from_archive)
