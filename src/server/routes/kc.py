"""HTTP adapter for the Knowledge Compiler path.

Two groups of endpoints live here:

* ``POST /api/v1/kc/compile`` — the minimal single-source compile path.
* ``GET  /api/v1/kc/book/status`` and ``POST /api/v1/kc/book/build`` — the
  Book view (book-build runtime wiring).

The Book endpoints are thin adapters. They hold no book logic beyond
request/response shaping; everything else is delegated to
:mod:`src.kc.views.book.materialize` (pure read) and
:mod:`src.kc.views.book.rebuild` (compile + render + staged commit). They
mirror the CLI in ``src.cli_ext.book_cmd`` and share its semantics:

* **Dry-run by default.** ``{"apply": true}`` is required to write. A book
  build touches every claim in the project, so an accidental mass write is
  expensive and hard to review.
* **Output dir (D-3)** defaults to ``<project_root>/book/``.
* **An empty project is not a success.** It returns ``200`` with
  ``status: "empty"`` rather than silently publishing a chapter-less book.

Status codes:

    200  ok — ``planned`` (dry-run), ``committed`` (apply), or ``empty``
    400  body is not a JSON object, or ``project_id`` is missing/invalid
    404  the project could not be resolved
    409  build failed — at least one chapter could not be compiled/rendered
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from ...kc.integrity.orchestrator import IntegrityGate
from ...kc.views.book import rebuild_book
from ...kc.views.book.materialize import materialize_book_snapshot
from ...lib.project import resolve_project
from ...project.context import ProjectNotFoundError
from src.kc.compiler.normalize import normalize_text

router = APIRouter(prefix="/api/v1/kc", tags=["knowledge-compiler"])

#: D-3 — default output directory, relative to the project root.
DEFAULT_OUTPUT_DIRNAME = "book"


# ─── Shared helpers ────────────────────────────────────────────────────


def _resolve_root(project_id: str) -> Path:
    """Resolve ``project_id`` to its project root; 404 when unresolvable."""
    try:
        ctx, _paths = resolve_project(project_id, by_id_only=True)
    except ProjectNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return Path(ctx.path)


def _chapter_list(snapshot) -> list[dict]:
    """Per-chapter summary rows for ``book/status``.

    ``get_ku`` returns ``None`` for unknown ids, so each lookup is guarded —
    a chapter whose KU went missing degrades to zero counts instead of
    raising (status must never fail because of a partially-written KC tree).
    """
    rows: list[dict] = []
    for chapter in snapshot.chapters:
        ku_ids = chapter.source_knowledge_unit_ids
        if not ku_ids:
            continue
        ku = snapshot.core_view.get_ku(ku_ids[0])
        rows.append(
            {
                "order": chapter.order,
                "chapter_id": chapter.id,
                "title": chapter.title,
                "stable_key": chapter.stable_key,
                "claims": len(ku.claim_ids) if ku is not None else 0,
                "evidence": len(snapshot.core_view.ku_evidence_ids(ku_ids[0])),
            }
        )
    return rows


def _empty_payload(snapshot, *, apply: bool) -> dict:
    """Response for a project with nothing to build."""
    return {
        "status": "empty",
        "apply": apply,
        "book_id": None,
        "title": snapshot.book.title,
        "publication_version": snapshot.publication_version,
        "chapter_count": snapshot.stats.chapter_count,
        "rebuilt_chapter_ids": [],
        "failed_chapter_ids": [],
        "reason_codes": list(snapshot.warning_codes),
        "output_dir": None,
    }


# ─── POST /compile (minimal path) ──────────────────────────────────────


@router.post("/compile")
async def compile_knowledge(body: dict):
    from src.kc.api import compile_source

    try:
        return await compile_source(
            str(body["source"]),
            document=normalize_text(str(body["content"]), source=str(body["source"])),
            candidate_json=str(body["candidate_json"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


# ─── GET /book/status ──────────────────────────────────────────────────


@router.get("/book/status")
async def book_status(project_id: str):
    """Describe what a ``book/build`` would produce. Read-only, never writes."""
    root = _resolve_root(project_id)
    snapshot = materialize_book_snapshot(root)

    return {
        "project_root": str(root),
        "empty": snapshot.is_empty,
        "derived": snapshot.derived,
        "book_id": snapshot.book.id,
        "title": snapshot.book.title,
        "publication_version": snapshot.publication_version,
        "chapters": snapshot.stats.chapter_count,
        "claims": snapshot.stats.claim_count,
        "evidence": snapshot.stats.evidence_count,
        "bundles": snapshot.stats.bundle_count,
        "knowledge_units": snapshot.stats.knowledge_unit_count,
        "skipped_objects": snapshot.stats.skipped_object_count,
        "reason_codes": list(snapshot.warning_codes),
        "chapter_list": _chapter_list(snapshot),
    }


# ─── POST /book/build ──────────────────────────────────────────────────


@router.post("/book/build")
async def book_build(request: Request):
    """Compile + render the Book view. Dry-run unless ``{"apply": true}``.

    The body is read via ``Request`` rather than a declared ``dict``
    parameter on purpose: a declared ``dict`` makes FastAPI answer ``422``
    for a JSON array, but a malformed body is a client error (``400``),
    not a validation error on a well-formed request.
    """
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 - empty / non-JSON body -> client error
        body = None
    if not isinstance(body, dict):
        raise HTTPException(400, "body must be a JSON object")

    project_id = body.get("project_id")
    if not isinstance(project_id, str) or not project_id.strip():
        raise HTTPException(400, "project_id is required")

    out = body.get("out")
    if out is not None and (not isinstance(out, str) or not out.strip()):
        raise HTTPException(400, "out must be a non-empty string")
    title = body.get("title")
    if title is not None and not isinstance(title, str):
        raise HTTPException(400, "title must be a string")

    root = _resolve_root(project_id)
    apply = bool(body.get("apply", False))
    snapshot = materialize_book_snapshot(root, book_title=title)

    if snapshot.is_empty:
        return _empty_payload(snapshot, apply=apply)

    # Only an applying run needs an output directory — a dry-run must not
    # leak a path that implies something was written.
    output_dir: Path | None = None
    if apply:
        output_dir = Path(out) if out else root / DEFAULT_OUTPUT_DIRNAME

    report = rebuild_book(
        snapshot.book,
        snapshot.chapters,
        snapshot.core_view,
        IntegrityGate(),
        output_dir=output_dir,
        apply=apply,
    )

    payload = {
        "status": report.status,
        "apply": apply,
        "book_id": report.book_id,
        "title": snapshot.book.title,
        "publication_version": report.publication_version,
        "chapter_count": len(report.rebuilt_chapter_ids),
        "rebuilt_chapter_ids": list(report.rebuilt_chapter_ids),
        "failed_chapter_ids": list(report.failed_chapter_ids),
        "reason_codes": list(report.reason_codes),
        "output_dir": str(output_dir) if output_dir is not None else None,
    }

    if report.status == "failed":
        # 409 with the payload at the top level (not wrapped in "detail")
        # so callers can read status/reason_codes without unwrapping.
        # A human-readable ``detail`` rides along because the web UI surfaces
        # ``data.detail`` as the error message — without it a failure would
        # degrade to a bare "409 Conflict".
        payload["detail"] = (
            f"Book build failed for {len(report.failed_chapter_ids)} chapter(s): "
            + (", ".join(report.reason_codes) or "unknown reason")
        )
        return JSONResponse(status_code=409, content=payload)
    return payload
