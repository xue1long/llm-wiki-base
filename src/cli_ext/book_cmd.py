"""``book`` CLI subcommand — build / show the Book view (book-build wiring, Task 2).

Makes "generate book" a reachable runtime path. Before this command the Book
compiler, renderer and rebuild pipeline were implemented and tested but only
drivable through ``scripts/kc_book_rebuild.py`` with a hand-written JSON
snapshot.

    python -m src.cli book show  --project <id>            # read-only plan
    python -m src.cli book build --project <id>            # dry-run (default)
    python -m src.cli book build --project <id> --apply    # write <root>/book/

Design decisions:

* **Dry-run by default.** ``--apply`` is required to write. Building a book
  touches every claim in the project; an accidental mass write is expensive
  and hard to review.
* **Output dir (D-3)** defaults to ``<project_root>/book/`` — matches the
  existing ``scripts/kc_book_rebuild.py`` convention, and keeps generated
  artifacts out of ``wiki/`` (which is the wiki's own source of truth).
* **Exit codes are distinguishable** so scripts can react: 0 ok, 1 rebuild
  failed, 2 project unresolved, 3 nothing to build. An empty project is NOT
  an error-0 success — silently publishing an empty book is worse than
  failing loudly.

The heavy lifting lives in :mod:`src.kc.views.book.materialize` (pure read)
and :mod:`src.kc.views.book.rebuild` (compile + render + staged commit).
This module only resolves the project, wires them together and reports.

Idempotency (verified by tests, worth knowing before scripting against it):

    Chapter ids are content hashes, so repeated builds REWRITE the same
    ``<chapter_id>.md`` / ``.json`` pair instead of littering the output
    directory with new files. The ``.json`` sidecar is byte-identical across
    runs, and ``rendered_hash`` — the content fingerprint — never changes.
    One exception: ``markdown._footer`` writes ``generated_at: <unix ms>``
    into each Markdown body, so the ``.md`` bytes differ by that single audit
    line on every run. Compare ``rendered_hash`` (not file bytes) to decide
    whether a build actually changed anything.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ..kc.integrity.orchestrator import IntegrityGate
from ..kc.views.book import rebuild_book
from ..kc.views.book.materialize import materialize_book_snapshot
from ..lib.project import resolve_project
from ..project.context import ProjectNotFoundError

# ── Exit-code contract ─────────────────────────────────────────────────
EXIT_OK: int = 0
EXIT_BUILD_FAILED: int = 1
EXIT_PROJECT_UNRESOLVED: int = 2
EXIT_NOTHING_TO_BUILD: int = 3

#: D-3 — default output directory, relative to the project root.
DEFAULT_OUTPUT_DIRNAME: str = "book"


# ─── Shared helpers ────────────────────────────────────────────────────


def _resolve(project_arg: str | None) -> Any:
    """Resolve the project; convert ProjectNotFoundError into exit code 2."""
    try:
        ctx, _paths = resolve_project(project_arg)
    except ProjectNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(EXIT_PROJECT_UNRESOLVED)
    return ctx


def _emit(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return None


def _empty_snapshot_error(snapshot, *, as_json: bool) -> None:
    """Report an empty (nothing-to-build) snapshot and exit 3."""
    reasons = ", ".join(snapshot.warning_codes) or "no claims found"
    if as_json:
        print(json.dumps({
            "status": "empty",
            "reason_codes": list(snapshot.warning_codes),
            "stats": _stats_dict(snapshot),
        }, ensure_ascii=False, indent=2))
    else:
        print(f"Nothing to build: {reasons}", file=sys.stderr)
    sys.exit(EXIT_NOTHING_TO_BUILD)


def _stats_dict(snapshot) -> dict[str, Any]:
    return {
        "bundles": snapshot.stats.bundle_count,
        "claims": snapshot.stats.claim_count,
        "evidence": snapshot.stats.evidence_count,
        "knowledge_units": snapshot.stats.knowledge_unit_count,
        "chapters": snapshot.stats.chapter_count,
        "skipped_objects": snapshot.stats.skipped_object_count,
        "source_paths": list(snapshot.stats.source_paths),
    }


# ─── book show ─────────────────────────────────────────────────────────


def cmd_book_show(args: argparse.Namespace) -> int:
    """Show what a ``book build`` would produce. Read-only, never writes."""
    ctx = _resolve(args.project)
    snapshot = materialize_book_snapshot(ctx.path)

    if snapshot.is_empty:
        _empty_snapshot_error(snapshot, as_json=args.json)

    chapter_list = [
        {
            "order": chapter.order,
            "chapter_id": chapter.id,
            "title": chapter.title,
            "stable_key": chapter.stable_key,
            "claims": len(snapshot.core_view.get_ku(
                chapter.source_knowledge_unit_ids[0]
            ).claim_ids) if chapter.source_knowledge_unit_ids else 0,
            "evidence": len(snapshot.ku_evidence_map.get(
                chapter.source_knowledge_unit_ids[0], ()
            )) if chapter.source_knowledge_unit_ids else 0,
        }
        for chapter in snapshot.chapters
    ]

    if args.json:
        print(json.dumps({
            "book_id": snapshot.book.id,
            "title": snapshot.book.title,
            "publication_version": snapshot.publication_version,
            "derived": snapshot.derived,
            "warning_codes": list(snapshot.warning_codes),
            "chapters": snapshot.stats.chapter_count,
            "claims": snapshot.stats.claim_count,
            "evidence": snapshot.stats.evidence_count,
            "chapter_list": chapter_list,
            "stats": _stats_dict(snapshot),
        }, ensure_ascii=False, indent=2))
        return EXIT_OK

    print(f"Book: {snapshot.book.title}  (id={snapshot.book.id})")
    print(f"  publication_version={snapshot.publication_version}  derived={snapshot.derived}")
    print(
        f"  chapters={snapshot.stats.chapter_count}  "
        f"claims={snapshot.stats.claim_count}  "
        f"evidence={snapshot.stats.evidence_count}  "
        f"bundles={snapshot.stats.bundle_count}"
    )
    if snapshot.warning_codes:
        print(f"  warning_codes: {', '.join(snapshot.warning_codes)}")
    print("Chapters:")
    for item in chapter_list:
        print(
            f"  [{item['order']}] {item['chapter_id']}  "
            f"claims={item['claims']}  evidence={item['evidence']}"
        )
        print(f"      stable_key={item['stable_key']}")
    return EXIT_OK


# ─── book build ────────────────────────────────────────────────────────


def cmd_book_build(args: argparse.Namespace) -> int:
    """Compile + render the Book view. Dry-run unless ``--apply``."""
    ctx = _resolve(args.project)
    snapshot = materialize_book_snapshot(ctx.path, book_title=args.title)

    if snapshot.is_empty:
        _empty_snapshot_error(snapshot, as_json=args.json)

    output_dir: Path | None = None
    if args.apply:
        output_dir = Path(args.out) if args.out else ctx.path / DEFAULT_OUTPUT_DIRNAME

    report = rebuild_book(
        snapshot.book,
        snapshot.chapters,
        snapshot.core_view,
        IntegrityGate(),
        output_dir=output_dir,
        apply=bool(args.apply),
    )

    payload = {
        "status": report.status,
        "apply": bool(args.apply),
        "book_id": report.book_id,
        "title": snapshot.book.title,
        "publication_version": report.publication_version,
        "rebuilt_chapter_ids": list(report.rebuilt_chapter_ids),
        "failed_chapter_ids": list(report.failed_chapter_ids),
        "reason_codes": list(report.reason_codes),
        "chapter_count": len(report.rebuilt_chapter_ids),
        "output_dir": str(output_dir) if output_dir is not None else None,
    }

    if report.status == "failed":
        if args.json:
            _emit(payload, as_json=True)
        else:
            print(
                f"Build failed: {len(report.failed_chapter_ids)} chapter(s) — "
                f"{', '.join(report.reason_codes)}",
                file=sys.stderr,
            )
            for chapter_id in report.failed_chapter_ids:
                print(f"  failed: {chapter_id}", file=sys.stderr)
        sys.exit(EXIT_BUILD_FAILED)

    if args.json:
        _emit(payload, as_json=True)
        return EXIT_OK

    print(f"Book: {snapshot.book.title}  (id={report.book_id})")
    print(f"  status={report.status}  publication_version={report.publication_version}")
    print(
        f"  planned={len(report.rebuilt_chapter_ids)}  "
        f"failed={len(report.failed_chapter_ids)}"
    )
    if output_dir is not None:
        print(f"  output_dir={output_dir}")
    else:
        print(f"  output_dir=(dry-run; re-run with --apply to write "
              f"{ctx.path / DEFAULT_OUTPUT_DIRNAME})")
    if report.reason_codes:
        print(f"  reason_codes: {', '.join(report.reason_codes)}")
    if not args.apply:
        print("  dry-run: nothing was written")
    return EXIT_OK


__all__ = [
    "DEFAULT_OUTPUT_DIRNAME",
    "EXIT_BUILD_FAILED",
    "EXIT_NOTHING_TO_BUILD",
    "EXIT_OK",
    "EXIT_PROJECT_UNRESOLVED",
    "cmd_book_build",
    "cmd_book_show",
]
