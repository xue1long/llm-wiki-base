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
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from ..kc.integrity.orchestrator import IntegrityGate
from ..kc.views.book import rebuild_book
from ..kc.views.book.materialize import materialize_book_manifest, materialize_book_plan, materialize_book_snapshot
from ..lib.project import resolve_project
from ..project.context import ProjectNotFoundError
from ..kc.views.book.wiki import run_preflight, LockBusyError
from ..kc.views.book.wiki.theme_outline import ThemeOutlineError, plan_theme_outline, save_theme_outline

# ── Exit-code contract ─────────────────────────────────────────────────
EXIT_OK: int = 0
EXIT_BUILD_FAILED: int = 1
EXIT_PROJECT_UNRESOLVED: int = 2
EXIT_NOTHING_TO_BUILD: int = 3
EXIT_SNAPSHOT_MISMATCH: int = 4
EXIT_LOCK_BUSY: int = 5
EXIT_BUDGET_EXHAUSTED: int = 6
EXIT_UNRESOLVED_RELATIONS: int = 7
EXIT_DISK_PRESSURE: int = 8
EXIT_QUALITY_GATE: int = 9
EXIT_RUBRIC_WARNING: int = 10

#: D-3 — default output directory, relative to the project root.
DEFAULT_OUTPUT_DIRNAME: str = "book"
DEFAULT_WIKI_OUTPUT_DIRNAME: str = "book-wiki"


def cmd_book_outline_from_theme(args: argparse.Namespace) -> int:
    """Generate a Wiki-independent volume/chapter skeleton."""
    ctx = _resolve(args.project)
    purpose_path = Path(args.purpose_file or (ctx.path / "purpose.md"))
    purpose = purpose_path.read_text(encoding="utf-8") if purpose_path.exists() else ""
    theme = (args.theme or purpose).strip()
    if not theme:
        print("Error: --theme or a non-empty purpose.md is required", file=sys.stderr)
        raise SystemExit(EXIT_BUILD_FAILED)
    try:
        from src.llm.provider_factory import create_llm_provider
        from src.llm.registry import ProviderRegistry
        provider_name = (
            getattr(args, "provider", None)
            or os.environ.get("RUFLO_LLM_PROVIDER", "").strip()
            or ProviderRegistry.get_default_name()
            or ""
        )
        outline = asyncio.run(plan_theme_outline(
            theme=theme, purpose=purpose,
            provider=create_llm_provider(provider_name),
        ))
    except Exception as exc:
        payload = {"status": "failed", "reason_codes": ["E_THEME_OUTLINE_FAILED"], "error": str(exc)}
        print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else f"Error: {exc}", file=sys.stderr)
        raise SystemExit(EXIT_BUILD_FAILED)
    output = Path(args.output or (ctx.path / ".llm-wiki" / "book" / "theme-outline.json"))
    if args.apply:
        save_theme_outline(output, outline)
    payload = {"status": "committed" if args.apply else "planned", "theme": theme,
               "outline": outline, "output": str(output), "apply": bool(args.apply)}
    print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else
          f"Theme outline: {len(outline['volumes'])} volumes → {sum(len(v['chapters']) for v in outline['volumes'])} chapters\noutput={output}")
    return EXIT_OK


def _wiki_exit_code(errors: tuple[Any, ...]) -> int:
    """Map preflight/compiler error codes to the stable CLI contract."""
    for error in errors:
        code = error if isinstance(error, str) else getattr(error, "code", "")
        code = str(code)
        normalized = code.upper()
        if code in {
            "E_PROJECT_UNRESOLVED", "E_PROJECT_NOT_FOUND",
            "E_PROJECT_NOT_INITIALIZED", "E_PROJECT_SCHEMA_MISMATCH",
            "E_PROJECT_JSON_CORRUPT", "project-not-found",
        }:
            return EXIT_PROJECT_UNRESOLVED
        if code in {"no-pages", "E_NO_ELIGIBLE_PAGES"}:
            return EXIT_NOTHING_TO_BUILD
        if "LOCK" in normalized:
            return EXIT_LOCK_BUSY
        if "BUDGET" in normalized or "TOKEN" in normalized or "PROVIDER" in normalized:
            return EXIT_BUDGET_EXHAUSTED
        if "UNRESOLVED" in normalized or "RELATION" in normalized:
            return EXIT_UNRESOLVED_RELATIONS
        if "DISK" in normalized or "SPACE" in normalized:
            return EXIT_DISK_PRESSURE
        if "QUALITY" in normalized or "GATE" in normalized:
            return EXIT_QUALITY_GATE
        if "RUBRIC" in normalized:
            return EXIT_RUBRIC_WARNING
        if "SNAPSHOT" in normalized or "FINGERPRINT" in normalized:
            return EXIT_SNAPSHOT_MISMATCH
    return EXIT_BUILD_FAILED


def cmd_book_build_from_wiki(args: argparse.Namespace) -> int:
    """Run the V3 wiki compiler; dry-run is the default."""
    ctx = _resolve(args.project)
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = ctx.path / output_dir

    preflight = run_preflight(
        str(ctx.path), output_dir=output_dir,
        use_llm=bool(args.use_llm), provider_name=getattr(args, "provider", None),
        polish=bool(args.polish),
    )
    if getattr(args, "encyclopedic", False) and not args.use_llm:
        payload = {"status": "blocked", "errors": [{"code": "E_ENCYCLOPEDIC_REQUIRES_LLM", "message": "--encyclopedic requires --use-llm"}], "output_dir": str(output_dir.resolve())}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print("Error [E_ENCYCLOPEDIC_REQUIRES_LLM]: --encyclopedic requires --use-llm", file=sys.stderr)
        raise SystemExit(EXIT_BUDGET_EXHAUSTED)
    if not preflight.ok:
        payload = {"status": "blocked", "errors": [e.__dict__ for e in preflight.errors],
                   "output_dir": str(output_dir.resolve())}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            for error in preflight.errors:
                print(f"Error [{error.code}]: {error.message}", file=sys.stderr)
        raise SystemExit(_wiki_exit_code(preflight.errors))

    try:
        from ..kc.views.book.wiki.compiler import build_from_wiki
    except ImportError as exc:
        payload = {"status": "failed", "reason_codes": ["E_COMPILER_UNAVAILABLE"],
                   "error": str(exc)}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print("Build failed: V3 wiki compiler is unavailable", file=sys.stderr)
        raise SystemExit(EXIT_BUILD_FAILED)

    try:
        result = build_from_wiki(
            ctx.path, output_dir=output_dir, use_llm=bool(args.use_llm),
            polish=bool(args.polish), apply=bool(args.apply),
            max_attempts=args.max_attempts, max_input_tokens=args.max_input_tokens,
            max_output_tokens=args.max_output_tokens,
            encyclopedic=bool(getattr(args, "encyclopedic", False)),
            quality_gate=getattr(args, "quality_gate", "rule"), rubric=getattr(args, "rubric", None),
            theme_outline=getattr(args, "theme_outline", None),
        )
    except LockBusyError:
        raise SystemExit(EXIT_LOCK_BUSY)
    except Exception as exc:
        if args.json:
            print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False, indent=2))
        else:
            print(f"Build failed: {exc}", file=sys.stderr)
        raise SystemExit(EXIT_BUILD_FAILED)

    payload = result if isinstance(result, dict) else getattr(result, "__dict__", {"status": "ok"})
    if not isinstance(payload, dict):
        payload = {"status": "ok", "result": str(payload)}
    if not args.apply:
        payload.setdefault("dry_run", True)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        print(f"Wiki book: {payload.get('status', 'ok')}")
        print(f"  output_dir={output_dir.resolve()}")
        if not args.apply:
            print("  dry-run: nothing was published")
    if payload.get("status") in {"failed", "blocked"}:
        codes = payload.get("errors", ()) or payload.get("reason_codes", ())
        raise SystemExit(_wiki_exit_code(tuple(codes)))
    if payload.get("warnings"):
        if args.json:
            raise SystemExit(EXIT_RUBRIC_WARNING)
        print("  warnings: " + ", ".join(payload["warnings"]), file=sys.stderr)
        raise SystemExit(EXIT_RUBRIC_WARNING)
    return EXIT_OK


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
        build_manifest=materialize_book_manifest(ctx.path) if getattr(args, "strict", False) else None,
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


def cmd_book_plan(args: argparse.Namespace) -> int:
    ctx = _resolve(args.project)
    plan = materialize_book_plan(ctx.path)
    payload = {
        "added_source_ids": list(plan.added_source_ids),
        "removed_source_ids": list(plan.removed_source_ids),
        "added_wiki_page_ids": list(plan.added_wiki_page_ids),
        "removed_wiki_page_ids": list(plan.removed_wiki_page_ids),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for key, values in payload.items():
            print(f"{key}: {', '.join(values) if values else '-'}")
    return EXIT_OK


__all__ = [
    "DEFAULT_OUTPUT_DIRNAME",
    "EXIT_BUILD_FAILED",
    "EXIT_NOTHING_TO_BUILD",
    "EXIT_OK",
    "EXIT_PROJECT_UNRESOLVED",
    "cmd_book_build",
    "cmd_book_build_from_wiki",
    "cmd_book_outline_from_theme",
    "cmd_book_plan",
    "cmd_book_show",
]
