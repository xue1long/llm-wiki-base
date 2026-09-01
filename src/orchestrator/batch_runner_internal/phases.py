"""Phase coroutines for batch orchestration."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from .gate import Batch
from .hooks import _crash_at, _fake_generate, _is_fake_mode, _snapshot_page_hashes
from .raw_lifecycle import _generate_raw, _is_immutable_source
from .state import _update_fail_streak
from src.services.batch_state import set_raw_status
from src.wiki.features.batch_gate import run_precommit_gate


async def _phase_generate(paths, provider, pending, batch_no, batch_key,
                          concurrency, runner=None):
    generated: dict[str, tuple[list, list, dict]] = {}
    raw_headers: dict[str, str] = {}
    failed_raws: list[str] = []
    perm_failed_raws: list[str] = []
    skipped_immutable: list[str] = []

    batch = Batch(batch_no=batch_no, files=pending)
    if runner is not None:
        runner._on_phase_start("generate", batch)

    async def _gen_one(raw_rel: str) -> None:
        set_raw_status(paths, batch_key, raw_rel, "in_progress")
        _crash_at("generate")
        try:
            if _is_immutable_source(paths, raw_rel):
                set_raw_status(paths, batch_key, raw_rel, "done",
                               skipped="immutable", branch="skip")
                skipped_immutable.append(raw_rel)
                return
            if os.environ.get("RUFLO_EXECUTOR_FAKE_GENERATE") == "1":
                pages = _fake_generate(raw_rel)
                meta = {
                    "fake": True,
                    "expected_page_hashes": _snapshot_page_hashes(paths, pages),
                }
                generated[raw_rel] = (pages, [], meta)
            else:
                pages, extras, meta = await _generate_raw(
                    paths, provider, raw_rel, batch_no)
                meta = dict(meta or {})
                meta["expected_page_hashes"] = _snapshot_page_hashes(paths, pages)
                generated[raw_rel] = (pages, extras, meta)
            header = ""
            try:
                header = (paths.root / raw_rel).read_text(
                    encoding="utf-8", errors="replace")[:4000]
            except OSError:
                pass
            raw_headers[raw_rel] = header
        except Exception as exc:
            from src.pipeline.retry import PermanentFailure
            if isinstance(exc, PermanentFailure):
                perm_failed_raws.append(raw_rel)
                set_raw_status(paths, batch_key, raw_rel, "permanent_failed",
                               last_error=str(exc))
            else:
                failed_raws.append(raw_rel)
                set_raw_status(paths, batch_key, raw_rel, "failed",
                               last_error=str(exc))

    sem = asyncio.Semaphore(concurrency)

    async def _gen_locked(raw_rel: str) -> None:
        async with sem:
            await _gen_one(raw_rel)

    await asyncio.gather(*(_gen_locked(raw) for raw in pending))
    for raw in failed_raws:
        _update_fail_streak(paths, batch_key, raw, "failed")
    for raw in perm_failed_raws:
        _update_fail_streak(paths, batch_key, raw, "permanent_failed")
    if runner is not None:
        runner._on_phase_end("generate", batch, None)
    return generated, raw_headers, failed_raws, perm_failed_raws, skipped_immutable


async def _phase_gate(paths, generated, raw_headers, pending, args, runner=None):
    batch = Batch(batch_no=args.batch, files=pending)
    if runner is not None:
        runner._on_phase_start("gate", batch)
    all_pages = [p for pages, _, _ in generated.values() for p in pages]
    all_extras = [e for _, extras, _ in generated.values() for e in extras]
    pending_gap_slugs = {
        m["slug"]
        for _, _, meta in generated.values()
        for m in (meta or {}).get("missing_slugs") or []
    }
    if not _is_fake_mode():
        from src.orchestrator.auto_tag import auto_tag_ugc
        tagged = auto_tag_ugc(all_pages, raw_headers)
        if tagged:
            print(f"  [auto-tag] {tagged} UGC-carrier-derived "
                  f"page(s) tagged 素材/ugc + 可信度/ugc", flush=True)
    batch_page_ids = sorted({p.id for p in all_pages})
    from src.utils.path import canonical_raw_key
    from src.wiki.features.target_resolver import ResolutionContext
    source_candidates = []
    for raw in pending:
        if raw not in generated:
            continue
        slug = (generated[raw][2] or {}).get("source_slug")
        if slug:
            source_candidates.append(
                (canonical_raw_key(raw, paths.root), slug, Path(raw).stem))
    resolution_context = (
        ResolutionContext(source_candidates=tuple(source_candidates))
        if source_candidates else None
    )
    gate_ok, gate_issues = run_precommit_gate(
        all_pages, all_extras, raw_headers, paths,
        allow_overwrite=args.allow_overwrite,
        pending_gap_slugs=pending_gap_slugs,
        resolution_context=resolution_context)
    if runner is not None:
        runner._on_phase_end("gate", batch, (gate_ok, gate_issues))
    return gate_ok, gate_issues, all_pages, batch_page_ids
