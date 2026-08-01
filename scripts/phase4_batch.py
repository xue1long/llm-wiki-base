"""phase4_batch.py — NDG Phase 4: generate → reconcile → gate → commit.

Consumes the backlog manifest, generates pages for one batch's files
through ``generate_ingest`` (NO writes), reconciles intra-batch conflicts,
runs the full NDG gate (P1-P7), and only commits when the gate passes.

Usage:
    env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
      PYTHONIOENCODING=utf-8 PYTHONPATH=. python scripts/phase4_batch.py \
      --batch 0 [--count 10] [--skip-gate] [--allow-overwrite]

Exit code: 0 = batch committed and gate passed; 2 = gate blocked.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

PROJECT_ID = "8dd46257-e46d-4bf8-b8d8-ba60b2aea54d"
ROOT = Path("knowledge/novel-wiki")
MANIFEST = ROOT / ".index" / "reingest_backlog.json"
BATCH_STATE = ROOT / ".index" / "batch_build_state.json"
REPORT = Path("scripts/_batch_report.txt")

_TYPE_DIR = {"source": "sources", "entity": "entities",
             "concept": "concepts", "synthesis": "synthesis"}

# NDG Phase 4: max retries for a single file before marking it failed.
MAX_RETRIES = 1
# NDG Phase 5.2: concurrent generate calls (LLM-bound, read-only — safe).
DEFAULT_CONCURRENCY = 3
# Hard per-file ceiling (seconds).  generate_ingest has its own LLM-phase
# timeout; this is an outer guard so a file that stalls anywhere (sanitize,
# reconcile, disk I/O) fails the file rather than hanging the batch.
FILE_TIMEOUT = 900


def _log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with REPORT.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _load_state() -> dict:
    """Read batch_build_state.json, tolerating a missing/unreadable/corrupt
    file (D4/B7): both tools read/write the same file, and a stale .tmp or
    partial write must not crash either of them."""
    try:
        if BATCH_STATE.exists():
            return json.loads(BATCH_STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {}


def _save_state(state: dict) -> None:
    """Atomically write batch state (tmp + os.replace to avoid corruption)."""
    import os as _os
    BATCH_STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = BATCH_STATE.with_suffix(BATCH_STATE.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    _os.replace(str(tmp), str(BATCH_STATE))


def _read_raw_header(raw_path: Path, chars: int = 4000) -> str:
    """Read the first *chars* characters of a raw file for UGC detection."""
    try:
        with raw_path.open("r", encoding="utf-8", errors="replace") as fh:
            return fh.read(chars)
    except OSError:
        return ""


def _batch_completed_files(batch_key: str) -> set[str]:
    """Return the set of raw file paths already completed for this batch.

    Status-independent read (D1/F7): any entry carrying ``completed_files``
    (``committing`` / ``partial`` / ``committed`` / ``postcheck_failed``)
    resumes from it.  ``gate_failed`` / ``failed`` entries carry none →
    correctly empty."""
    state = _load_state()
    entry = state.get(batch_key)
    if isinstance(entry, dict):
        return set(entry.get("completed_files", []))
    return set()


def _decide_abort(
    ok: int,
    err: int,
    pending: int,
    resume: bool,
    completed: set,
    skip: int,
) -> tuple[bool, str]:
    """R0-2: decide whether to abort the batch after the generate summary.

    A batch that produced zero pages must not fake-commit ``committed`` (B4).
    The only legitimate ``ok==0`` case is a ``--resume`` re-run where every
    file was already completed in a prior run (then there is nothing left to
    do, and the batch is already recorded as done).

    Params:
      ok        number of files successfully generated
      err       number of files that failed generation
      pending   number of files still pending — missing on disk this run
      resume    whether ``--resume`` was given
      completed set of raw paths already completed in a prior run
      skip      number of files skipped as already-completed (resume)

    Returns ``(abort, reason)``.
    """
    if ok == 0 and err > 0:
        return True, "all files failed"
    if ok == 0 and err == 0:
        if pending:
            return True, "all files missing (empty batch)"
        if resume and skip and len(completed) >= skip:
            return False, "all files already completed (resume)"
    return False, ""


def _check_overwrite_protection(
    pages: list,
    paths,
    allow_overwrite: bool,
) -> list[str]:
    """B6: check every batch page against the existing wiki index.

    Returns a list of blocker messages (empty → all clear).
    - Stub overwrite → always allowed (stub→real upgrade by design).
    - Non-stub overwrite → blocked unless ``--allow-overwrite``.
    """
    from src.wiki.features.indexer import read_index
    from src.wiki.storage.page_writer import read_page, page_path_for

    # Build {slug: type} for the existing wiki on disk
    existing: dict[str, str] = {}
    for entry in read_index(paths):
        slug, ptype, _title = entry[0], entry[1], entry[2] if len(entry) > 2 else ""
        existing[slug] = ptype.value if hasattr(ptype, "value") else str(ptype)

    blockers: list[str] = []
    for p in pages:
        if not p.id:
            continue
        ptype = p.type.value if hasattr(p.type, "value") else str(p.type)
        existing_type = existing.get(p.id)
        if existing_type is None:
            continue  # new slug, no conflict

        # Check if the on-disk page is a stub
        try:
            from src.wiki.core.types import PageType as PT
            disk_type = getattr(PT, existing_type.upper(), p.type)
            disk_page = read_page(page_path_for(paths, disk_type, p.id))
            if disk_page.processing_depth == "stub":
                # Stub upgrade — verify type matches
                if existing_type != ptype:
                    blockers.append(
                        f"Stub {p.id!r} is {existing_type} but new page "
                        f"is {ptype} — cannot upgrade across types."
                    )
                    continue
                # Same-type stub → real upgrade (by design)
                continue
        except FileNotFoundError:
            # Listed in index but missing on disk → stale index, treat as free
            continue
        except Exception:
            pass

        msg = (
            f"Page {p.id!r} ({ptype}) already exists on disk as "
            f"{existing_type} — would overwrite a non-stub page."
        )
        if allow_overwrite:
            _log(f"  WARN overwrite: {msg}")
        else:
            blockers.append(msg)

    return blockers


async def main() -> int:
    # Make pipeline INFO logs visible so batch progress is observable
    # (unified produced / creating stubs / etc.).  Without a handler the
    # ``logging`` INFO records are silently dropped and a slow-but-healthy
    # batch looks hung.
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )
    ap = argparse.ArgumentParser(
        description="NDG batch: generate → reconcile → gate → commit")
    ap.add_argument("--manifest", default=str(MANIFEST))
    ap.add_argument("--batch", type=int, default=0)
    ap.add_argument("--count", type=int, default=None)
    ap.add_argument("--project", default=PROJECT_ID)
    ap.add_argument("--skip-gate", action="store_true")
    ap.add_argument("--allow-overwrite", action="store_true")
    ap.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    ap.add_argument("--resume", action="store_true",
                    help="skip files already completed in a prior partial run")
    args = ap.parse_args()

    if not Path(args.manifest).exists():
        _log(f"manifest missing: {args.manifest}")
        return 1
    data = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    batches = data["batches"]
    if args.batch >= len(batches):
        _log(f"batch {args.batch} out of range (0..{len(batches)-1})")
        return 1
    batch = batches[args.batch]
    files = batch["files"]
    if args.count is not None:
        files = files[:args.count]
    _log(f"batch {args.batch} [{batch['theme']}]: {len(files)} file(s)")

    from src.pipeline import _get_provider, _resolve_wiki_paths
    from src.pipeline.ingest import generate_ingest, commit_ingest
    from src.utils.path import normalize_source_path
    from src.wiki.features.batch_reconcile import reconcile_batch
    from src.wiki.features.ndg_gate import run_ndg_gate

    paths = _resolve_wiki_paths(args.project)
    provider = _get_provider(args.project)
    _log(f"provider: {type(provider).__name__}")

    # ── Phase 5.2: generate all (concurrent, no writes) ─────────────
    # Checkpoint resume: skip files already completed in a prior run.
    batch_key = f"batch_{args.batch}"
    completed_files: set[str] = set()
    if args.resume:
        completed_files = _batch_completed_files(batch_key)
        if completed_files:
            _log(f"resume: skipping {len(completed_files)} already-completed file(s)")

    all_pages: list = []
    all_extra: list = []
    raw_headers: dict[str, str] = {}
    file_results: dict[str, dict] = {}  # raw_rel → {ok, pages, stubs, ...}
    t0 = time.time()
    sem = asyncio.Semaphore(args.concurrency)

    # Filter out completed files and missing files
    pending: list[tuple[int, str]] = []
    missing_count = 0
    completed_skip_count = 0
    for raw_rel in files:
        if args.resume and raw_rel in completed_files:
            completed_skip_count += 1
            _log(f"SKIP completed: {raw_rel}")
            continue
        src = ROOT / raw_rel
        if not src.is_file():
            missing_count += 1
            _log(f"SKIP missing: {raw_rel}")
            continue
        pending.append((len(pending), raw_rel))

    _log(f"generating {len(pending)} file(s) with concurrency={args.concurrency} "
         f"(skipped {len(files) - len(pending)})")

    async def _ingest_one(idx: int, raw_rel: str) -> tuple[str, object]:
        async with sem:
            src = ROOT / raw_rel
            text = src.read_text(encoding="utf-8", errors="replace")
            task_id = f"b{args.batch}-{Path(raw_rel).stem[:30]}"
            header = _read_raw_header(src)

            pages = extra = meta = None
            last_err = None
            for attempt in range(MAX_RETRIES + 1):
                try:
                    pages, extra, meta = await asyncio.wait_for(
                        generate_ingest(
                            paths=paths, source_path=Path(raw_rel),
                            source_text=text, provider=provider,
                            folder_context="", task_id=task_id,
                        ),
                        timeout=FILE_TIMEOUT,
                    )
                    last_err = None
                    break
                except Exception as exc:
                    last_err = exc
                    if attempt < MAX_RETRIES:
                        await asyncio.sleep(2)

            result = {
                "raw_rel": raw_rel,
                "header": header,
                "pages": pages,
                "extra": extra,
                "meta": meta,
                "ok": last_err is None,
                "error": str(last_err) if last_err else None,
            }
            return raw_rel, result

    tasks = [_ingest_one(i, r) for i, r in pending]
    gathered = await asyncio.gather(*tasks, return_exceptions=True)

    ok = err = 0
    for item in gathered:
        if isinstance(item, BaseException):
            err += 1
            _log(f"  UNHANDLED: {type(item).__name__}: {item}")
            continue
        raw_rel, result = item
        # Normalise the raw path key to match the source page's sources
        # field.  generate_ingest receives Path(raw_rel) and builds the
        # source page with normalize_source_path(str(Path(raw_rel)), root).
        # We replicate that exact normalization here so the gate key
        # matches what the source page stores in its sources field.
        _norm_key = normalize_source_path(str(Path(raw_rel)), paths.root)
        raw_headers[_norm_key] = result["header"]
        file_results[raw_rel] = result

        if result["ok"]:
            ok += 1
            stubs = sum(1 for p in (result["pages"] or [])
                        if getattr(p, "processing_depth", "") == "stub")
            _log(f"  OK {raw_rel}: {len(result['pages'])} pages, stubs={stubs}, "
                 f"rejected={result['meta'].get('rejected') if result['meta'] else '?'}")
            all_pages.extend(result["pages"] or [])
            all_extra.extend(result["extra"] or [])
        else:
            err += 1
            _log(f"  FAIL {raw_rel}: {result['error']}")

    _log(f"generated ok={ok} err={err} total_pages={len(all_pages)} "
         f"extras={len(all_extra)} elapsed={time.time()-t0:.0f}s")

    abort, reason = _decide_abort(
        ok=ok, err=err, pending=missing_count,
        resume=args.resume, completed=completed_files,
        skip=completed_skip_count,
    )
    if abort:
        _log(f"BATCH ABORTED: {reason}")
        state = _load_state()
        state[batch_key] = {
            "status": "failed",
            "files": files,
            "ok": ok, "err": err,
            "missing": missing_count,
            "skipped_completed": completed_skip_count,
            "reason": reason,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        _save_state(state)
        return 1

    # ── Phase 4.2: batch reconcile ─────────────────────────────────
    result = reconcile_batch(all_pages, all_extra, paths=paths)
    if result.stubs_suppressed:
        _log(f"reconcile: suppressed {result.stubs_suppressed} stub(s)")
    for m in result.merged:
        _log(f"reconcile: merged {m.dropped!r} → {m.kept!r} ({m.reason})")
    for c in result.conflicts:
        _log(f"reconcile: CONFLICT {c.slug!r} types={c.types}")

    # ── NDG gate (P1-P7) ──────────────────────────────────────────
    gate_rc = 0
    if not args.skip_gate:
        if result.conflicts:
            _log(f"gate: {len(result.conflicts)} cross-type slug conflict(s) → FAIL")
            gate_rc = 1
        else:
            # result.pages holds only the batch's own pages; result.extras
            # are the pre-existing pages kept by reconcile (R1-2).  P7 checks
            # the extras against the on-disk state; the batch pages are gated
            # as-is.
            report = run_ndg_gate(
                result.pages,
                raw_headers=raw_headers,
                extra_pages=result.extras,
                paths=paths,
                allow_overwrite=args.allow_overwrite,
            )
            _log(f"gate: {report.page_count} page(s) "
                 f"{'PASS' if report.passed else 'FAIL'} "
                 f"({len(report.issues)} issue(s), "
                 f"{report.blocker_count} blocker(s))")
            for issue in report.issues:
                tag = "BLOCK" if issue.is_blocker else "WARN"
                _log(f"  [{tag}] {issue.code} {issue.page_id or '-'}: {issue.message}")
            gate_rc = 0 if report.passed else 1

    if gate_rc != 0:
        _log("BATCH BLOCKED: gate failed — zero wiki writes (generate was dry)")
        # Save state so the operator can retry
        state = _load_state()
        state[f"batch_{args.batch}"] = {
            "status": "gate_failed",
            "files": files,
            "ok": ok, "err": err,
            "conflicts": [(c.slug, list(c.types)) for c in result.conflicts],
            "merged_count": len(result.merged),
            "stubs_suppressed": result.stubs_suppressed,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        _save_state(state)
        return 2

    # ── B6: overwrite protection (check against existing wiki) ──────
    overwrite_blockers = _check_overwrite_protection(
        result.pages, paths, args.allow_overwrite)
    if overwrite_blockers:
        _log(f"B6 overwrite protection: {len(overwrite_blockers)} blocker(s)")
        for msg in overwrite_blockers:
            _log(f"  BLOCK {msg}")
        _log("BATCH BLOCKED: overwrite protection — use --allow-overwrite to force")
        state = _load_state()
        state[batch_key] = {
            "status": "overwrite_blocked",
            "files": files,
            "ok": ok, "err": err,
            "overwrite_blockers": overwrite_blockers,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        _save_state(state)
        return 2

    # ── Commit (only if gate passed + overwrite check OK) ───────────
    _log(f"committing {len(result.pages)} reconciled page(s) ...")
    t_commit = time.time()

    # Group pages by source_path so we can call commit_ingest per file
    # (commit_ingest writes index + log once per source file).
    by_source: dict[str, list] = {}
    source_order: list[str] = []
    for p in result.pages:
        src = (p.sources or ["(unknown)"])[0]
        if src not in by_source:
            by_source[src] = []
            source_order.append(src)
        by_source[src].append(p)

    # Assign extra pages to the first source for commit purposes
    committed = 0
    for src in source_order:
        spages = by_source[src]
        # For the real source_path, resolve back from the project-relative form
        try:
            sp = ROOT / src
        except Exception:
            sp = Path(src)
        await commit_ingest(paths, sp, spages, task_id=f"b{args.batch}")
        committed += len(spages)

    _log(f"committed {committed} page(s) in {time.time()-t_commit:.0f}s")

    # ── Post-commit sanity (zero LLM cost) ────────────────────────
    from src.wiki.features.indexer import read_index
    from src.wiki.storage.page_writer import page_path_for
    _post_errors = 0
    _index_ids = {e[0] for e in read_index(paths)}
    for _p in result.pages:
        _pp = page_path_for(paths, _p.type, _p.id)
        if not _pp.exists():
            _log(f"POSTCHECK MISSING: {_p.id} — file not on disk")
            _post_errors += 1
        elif _p.id not in _index_ids:
            _log(f"POSTCHECK NOT-IN-INDEX: {_p.id}")
            _post_errors += 1
    if _post_errors:
        _log(f"POSTCHECK: {_post_errors} error(s) — review before next batch")
    else:
        _log("POSTCHECK: all pages on disk and indexed")

    # Save completion state
    state = _load_state()
    state[f"batch_{args.batch}"] = {
        "status": "committed",
        "files": files,
        "ok": ok, "err": err,
        "merged": [(m.kept, m.dropped, m.reason) for m in result.merged],
        "stubs_suppressed": result.stubs_suppressed,
        "page_count": len(result.pages),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    _save_state(state)

    _log(f"BATCH DONE ok={ok} err={err} pages={len(result.pages)} gate=PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
