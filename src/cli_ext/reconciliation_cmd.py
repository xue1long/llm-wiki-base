"""Task 31 — Reconciliation CLI subcommands.

Public surface:

  * :py:func:`cmd_reconcile`            — ruflo reconcile --project-root P
                                          process all pages in the project.
  * :py:func:`cmd_show_canonical`       — ruflo show-canonical <id>
  * :py:func:`cmd_list_canonicals`      — ruflo list-canonicals [--all]
  * :py:func:`cmd_undo`                 — ruflo undo <page_id> [--canonical <id>]
  * :py:func:`register`                 — argparse registration helper;
                                          the main session wires this into
                                          ``src/cli.py`` (no auto-wiring
                                          here, to keep this module
                                          independently importable for tests
                                          and to avoid multi-subagent cli.py
                                          merge conflicts).

CLI exit codes
--------------
Per spec §4 Task 31:

    0 — success
    2 — partial success: errors > 0 AND processed > 0
        (technical failures during the batch)

A fully empty batch (processed == 0, errors == 0) is exit code 0 —
nothing went wrong, there just was nothing to do.

Wiring constraints
------------------
This module does NOT import or modify ``src/cli.py``. The parent
session is responsible for wiring :py:func:`register` into the main
``argparse`` tree. Tests call the ``cmd_*`` functions directly with
hand-built :py:class:`argparse.Namespace` objects, which avoids
needing a top-level parser in unit tests.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from ..reconciliation.canonical_models import (
    CanonicalConcept,
    ReconciliationStatus,
)
from ..reconciliation.canonical_registry import CanonicalRegistry


# ---------------------------------------------------------------------------
# reconcile — main entry
# ---------------------------------------------------------------------------


def cmd_reconcile(args: argparse.Namespace) -> int:
    """``ruflo reconcile --project-root PATH``: process all project pages.

    Iterates the project's wiki pages, runs the per-page pipeline
    (retrieve_candidates → resolve_identity → apply_decisions) and
    prints aggregate metrics as JSON to stdout.

    Exit codes:

      * 0 — success (no errors)
      * 2 — errors > 0 but at least one page was processed
    """
    project_root = Path(args.project_root)
    resolver_fingerprint = getattr(args, "resolver_fingerprint", "") or ""

    # Page discovery: enumerate markdown files under <root>/wiki/.
    # This is the same shape ``src/wiki`` uses; Phase 1 stays
    # deliberately simple and does not need the full wiki loader.
    wiki_dir = project_root / "wiki"
    page_ids: list[str] = []
    if wiki_dir.exists():
        for md in sorted(wiki_dir.rglob("*.md")):
            # Skip index.md / log.md (catalog + audit) — they are not
            # reconcilable pages.
            if md.name in {"index.md", "log.md"}:
                continue
            stem = md.stem
            # Use the file stem as the page id (the wiki loader would
            # give us the real id, but Phase 1 uses the filename).
            page_ids.append(stem)

    if not page_ids:
        # Empty project — nothing to do. Emit a metrics JSON and exit 0.
        result = {
            "processed": 0,
            "created_new": 0,
            "joined_existing": 0,
            "unresolved": 0,
            "errors": 0,
            "touched_canonical_ids": [],
            "phase1_closed_loop": True,
        }
        print(json.dumps(result, ensure_ascii=False))
        return 0

    # Lazy imports: keep module import cheap and avoid pulling in the
    # resolver at import time (test files don't need it).
    from ..reconciliation.reconcile_job import reconcile_pages

    # Minimal page shim: Phase 1 reads ``.id`` / ``.title`` / ``.body``
    # / ``.slots`` off the page object. For Phase 1 we use the file
    # stem as id and the filename as the title (the wiki loader will
    # be plugged in once we move beyond Phase 1).
    pages: list[Any] = []
    for pid in page_ids:
        md_path = wiki_dir / f"{pid}.md"
        try:
            body = md_path.read_text(encoding="utf-8")
        except Exception:
            body = ""
        pages.append(_PageShim(pid=pid, title=pid, body=body))

    body_by_page = {p.id: p.body for p in pages}
    llm = getattr(args, "llm", None) or _NullLLM()

    result = asyncio.run(
        reconcile_pages(
            pages,
            project_root=project_root,
            llm=llm,
            body_by_page=body_by_page,
            language=getattr(args, "language", "") or "",
            resolver_fingerprint=resolver_fingerprint,
        )
    )

    payload = {
        "processed": result.processed,
        "created_new": result.created_new,
        "joined_existing": result.joined_existing,
        "unresolved": result.unresolved,
        "errors": result.errors,
        "touched_canonical_ids": list(result.touched_canonical_ids),
        "phase1_closed_loop": True,
    }
    print(json.dumps(payload, ensure_ascii=False))
    if result.errors and result.processed:
        return 2
    return 0


# ---------------------------------------------------------------------------
# show / list / undo
# ---------------------------------------------------------------------------


def cmd_show_canonical(args: argparse.Namespace) -> int:
    """``ruflo show-canonical <id>``: format-print a canonical concept."""
    project_root = Path(args.project_root)
    canonical_id = args.canonical_id
    registry = CanonicalRegistry(project_root)
    cc = registry.get_concept(canonical_id)
    if cc is None:
        print(
            f"ERROR: canonical {canonical_id!r} not found",
            file=sys.stderr,
        )
        return 2
    _print_canonical(cc)
    return 0


def cmd_list_canonicals(args: argparse.Namespace) -> int:
    """``ruflo list-canonicals [--all]``: list canonical concepts."""
    project_root = Path(args.project_root)
    registry = CanonicalRegistry(project_root)
    concepts = registry.load_concepts()
    if not concepts:
        print("(no canonical concepts)")
        return 0
    active_only: bool = bool(getattr(args, "active_only", True))
    rows: list[CanonicalConcept] = []
    for cc in concepts.values():
        if active_only and cc.status not in {
            ReconciliationStatus.ACTIVE,
            ReconciliationStatus.PENDING,
        }:
            continue
        rows.append(cc)
    rows.sort(key=lambda c: (c.status.value, c.canonical_id))
    if not rows:
        print("(no active canonical concepts)")
        return 0

    # Header
    print(
        f"{'CANONICAL_ID':<24}  {'STATUS':<11}  {'LABEL':<30}  MEMBERS"
    )
    print("-" * 90)
    for cc in rows:
        label = cc.preferred_label or "(no label)"
        members = str(len(cc.member_page_ids))
        print(
            f"{cc.canonical_id:<24}  {cc.status.value:<11}  "
            f"{label[:30]:<30}  {members}"
        )
    return 0


def cmd_undo(args: argparse.Namespace) -> int:
    """``ruflo undo <page_id> [--canonical <id>]``: remove membership.

    Without ``--canonical``, the command scans the registry for the
    first ACTIVE canonical that owns ``page_id`` and removes the
    membership from there.
    """
    project_root = Path(args.project_root)
    page_id = args.page_id
    canonical_id = getattr(args, "canonical_id", None)

    registry = CanonicalRegistry(project_root)

    if not canonical_id:
        # Find the first ACTIVE canonical that has page_id as a member.
        concepts = registry.load_concepts()
        match: CanonicalConcept | None = None
        for cc in concepts.values():
            if cc.status is not ReconciliationStatus.ACTIVE:
                continue
            if page_id in cc.member_page_ids:
                match = cc
                break
        if match is None:
            print(
                f"ERROR: page_id {page_id!r} not found in any ACTIVE canonical",
                file=sys.stderr,
            )
            return 2
        canonical_id = match.canonical_id

    removed = registry.remove_membership(page_id, canonical_id)
    if not removed:
        print(
            f"ERROR: page_id {page_id!r} was not a member of "
            f"{canonical_id!r}",
            file=sys.stderr,
        )
        return 2

    print(
        f"Removed page_id={page_id!r} from canonical={canonical_id!r}"
    )
    return 0


# ---------------------------------------------------------------------------
# Argparse registration
# ---------------------------------------------------------------------------


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the 4 reconciliation subcommands on ``subparsers``.

    Layout:

        ruflo reconcile --project-root PATH [--resolver-fingerprint FP]
        ruflo show-canonical --project-root PATH <canonical_id>
        ruflo list-canonicals --project-root PATH [--all]
        ruflo undo --project-root PATH <page_id> [--canonical <id>]
    """
    # reconcile
    p_reconcile = subparsers.add_parser(
        "reconcile",
        help="Run reconciliation Phase 1 over the project's pages",
    )
    p_reconcile.add_argument(
        "--project-root", type=Path, required=True,
        help="Path to the project root",
    )
    p_reconcile.add_argument(
        "--resolver-fingerprint", type=str, default="",
        help="F4 fingerprint wired into the decision log",
    )
    p_reconcile.add_argument(
        "--language", type=str, default="",
        help="ISO 639-1 language code forwarded to apply_decisions",
    )
    p_reconcile.set_defaults(func=cmd_reconcile)

    # show-canonical
    p_show = subparsers.add_parser(
        "show-canonical",
        help="Show the details of a single canonical concept",
    )
    p_show.add_argument(
        "--project-root", type=Path, required=True,
    )
    p_show.add_argument(
        "canonical_id", type=str,
        help="The canonical_id to display",
    )
    p_show.set_defaults(func=cmd_show_canonical)

    # list-canonicals
    p_list = subparsers.add_parser(
        "list-canonicals",
        help="List canonical concepts (default: active + pending only)",
    )
    p_list.add_argument(
        "--project-root", type=Path, required=True,
    )
    p_list.add_argument(
        "--all", dest="active_only", action="store_false",
        help="Include STALE / TOMBSTONED concepts",
    )
    p_list.set_defaults(active_only=True)
    p_list.set_defaults(func=cmd_list_canonicals)

    # undo
    p_undo = subparsers.add_parser(
        "undo",
        help="Remove a page from a canonical's membership (reversible)",
    )
    p_undo.add_argument(
        "--project-root", type=Path, required=True,
    )
    p_undo.add_argument(
        "page_id", type=str,
        help="The wiki page_id to detach",
    )
    p_undo.add_argument(
        "--canonical", dest="canonical_id", type=str, default=None,
        help="Target canonical_id (auto-detected from page_id when omitted)",
    )
    p_undo.set_defaults(func=cmd_undo)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class _PageShim:
    """Minimal page object for Phase 1 reconcile.

    The real wiki loader will replace this once Phase 2 lands; for
    Phase 1 we just need ``.id`` / ``.title`` / ``.body`` / ``.slots``
    to flow through to ``resolve_identity`` / ``build_evidence_pack``.
    """

    def __init__(self, *, pid: str, title: str, body: str) -> None:
        self.id = pid
        self.title = title
        self.body = body
        self.slots = {}


class _NullLLM:
    """No-op LLM shim for the empty-project / dry-run path.

    When the project has zero pages (or the user passes ``--dry-run``),
    we never actually call the LLM — but ``reconcile_pages`` still
    receives an ``llm`` argument. This class implements the minimum
    surface (``async complete``) and returns empty verdicts, which is
    the same behaviour the test fixture's FakeLLM provides.
    """

    async def complete(
        self,
        *,
        prompt_kind: str,
        user_prompt: str,
        system_prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        return '{"verdicts": []}'


def _print_canonical(cc: CanonicalConcept) -> None:
    """Format-print a canonical concept (used by ``show-canonical``)."""
    print(f"canonical_id   : {cc.canonical_id}")
    print(f"preferred_label: {cc.preferred_label or '(none)'}")
    print(f"status         : {cc.status.value}")
    print(f"version        : {cc.version}")
    print(f"resolver_fp    : {cc.resolver_fingerprint or '(none)'}")
    print(f"aliases        : {', '.join(cc.aliases) if cc.aliases else '(none)'}")
    print(f"members        : {len(cc.member_page_ids)}")
    for pid in cc.member_page_ids:
        print(f"  - {pid}")
    if cc.claim_ids:
        print(f"claim_ids      : {', '.join(cc.claim_ids)}")
    if cc.relation_ids:
        print(f"relation_ids   : {', '.join(cc.relation_ids)}")
    print(f"created_at_ms  : {cc.created_at_ms}")
    print(f"updated_at_ms  : {cc.updated_at_ms}")


__all__ = [
    "cmd_reconcile",
    "cmd_show_canonical",
    "cmd_list_canonicals",
    "cmd_undo",
    "register",
]