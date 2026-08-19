"""phase4_batch.py — NDG Phase 4: generate → reconcile → gate → commit.

Consumes the backlog manifest, generates pages for one batch's files
through ``generate_ingest`` (NO writes), reconciles intra-batch conflicts,
runs the NDG gate (P5-P7), and only commits when the gate passes.  Commit is
per-file (one ``commit_ingest`` per raw file), each group's success is
atomically recorded in ``completed_files`` so ``--resume`` regenerates only
the remaining files.

Usage:
    env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
      PYTHONIOENCODING=utf-8 PYTHONPATH=. python scripts/phase4_batch.py \
      --batch 0 [--count 10] [--skip-gate] [--allow-overwrite] \
      [--resume] [--skip-files raw/a.md,raw/b.md]

Exit codes:
  0  batch committed and POSTCHECK passed
  1  manifest / batch arg error, or the batch aborted (zero pages generated)
  2  gate blocked (NDG gate P5-P7 / B6 overwrite protection)
  3  POSTCHECK failed — pages missing after commit; --resume to fill them
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

# NDG Phase 4: max retries for a single file before marking it failed.
MAX_RETRIES = 1
# NDG Phase 5.2: concurrent generate calls (LLM-bound, read-only — safe).
DEFAULT_CONCURRENCY = 3
# Hard per-file ceiling (seconds).  generate_ingest has its own LLM-phase
# timeout; this is an outer guard so a file that stalls anywhere (sanitize,
# reconcile, disk I/O) fails the file rather than hanging the batch.
FILE_TIMEOUT = 900
# C7: warn when a single batch exceeds this wall-clock budget.
BATCH_WARN_SECONDS = 60 * 60

# C1 (plan 1.9): llm 熔断器名称与恢复轮询间隔。
LLM_BREAKER = "llm"
BREAKER_POLL_SECONDS = 5.0


def _log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with REPORT.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


async def _await_breaker_recovery(breaker=None, poll_seconds: float = BREAKER_POLL_SECONDS) -> None:
    """llm 熔断器 OPEN 时暂停整批，等待恢复（C1 / plan 1.9 O3）。

    直跑路径不再"OPEN 后照打"：executor 顶层在派发前检查 breaker，OPEN 则
    阻塞等待 —— ``can_execute()`` 在 recovery_timeout（60s）后自动转
    HALF_OPEN 放行试探调用，2 次成功恢复 CLOSED。禁止无冷却人工重启打满调用。
    """
    from src.circuit_breaker import CircuitState, get_circuit_breaker
    breaker = breaker or get_circuit_breaker(LLM_BREAKER)
    while not breaker.can_execute():
        _log(
            f"llm circuit breaker OPEN — pausing batch, waiting for recovery "
            f"({breaker.config.recovery_timeout}s cooldown) ..."
        )
        await asyncio.sleep(poll_seconds)
    if breaker.state != CircuitState.CLOSED:
        _log(f"llm circuit breaker now {breaker.state.value} — resuming batch")


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


def _preserve_ledger(prior: dict, entry: dict) -> dict:
    """Merge a new batch entry over the prior entry, keeping the resume
    ledger (``completed_files`` / ``failed_files``) from any earlier run.

    Failure branches (abort / gate_failed / overwrite_blocked) write
    wholesale status entries; without this merge they clobber the
    ``completed_files`` a crashed ``committing`` run recorded, so a later
    ``--resume`` regenerates already-committed files and trips B6.
    """
    return {
        "completed_files": entry.get("completed_files", prior.get("completed_files", [])),
        "failed_files": prior.get("failed_files", []),
        **{k: v for k, v in entry.items() if k not in ("completed_files", "failed_files")},
    }


def _save_state_entry(batch_key: str, entry: dict) -> None:
    """Persist a batch entry, preserving the resume ledger from prior runs."""
    state = _load_state()
    state[batch_key] = _preserve_ledger(state.get(batch_key, {}), entry)
    _save_state(state)


def _read_raw_header(raw_path: Path, chars: int = 4000) -> str:
    """Read the first *chars* characters of a raw file for UGC detection."""
    try:
        with raw_path.open("r", encoding="utf-8", errors="replace") as fh:
            return fh.read(chars)
    except OSError:
        return ""


def _batch_key(manifest: str, batch: int) -> str:
    """Manifest-bound state key (P1 fix), backward-compatible with the
    default manifest.

    The default manifest (``reingest_backlog.json``) keeps the legacy
    ``batch_{batch}`` key so existing consumers (``phase3_accept`` reads
    ``batch_0``) and already-committed state entries stay valid.  Any
    *alternate* manifest gets a stem-bound key ``batch_{stem}_{batch}`` so
    different manifests sharing a batch index no longer collide in
    ``batch_build_state.json`` — the original bug, where ``--resume`` could
    reuse the wrong manifest's ``completed_files``.
    """
    if Path(manifest).resolve() == Path(str(MANIFEST)).resolve():
        return f"batch_{batch}"
    return f"batch_{Path(manifest).stem}_{batch}"


def _resolve_batch_entry(state: dict, manifest: str, batch: int) -> dict | None:
    """Resolve a batch's state entry, bound to ``manifest``.

    Looks up the manifest-bound key first, then falls back to the legacy
    unbound key (``batch_{batch}``) so batches already committed before this
    change stay resumable.  Returns the entry dict, or ``None`` when neither
    exists (fresh run)."""
    entry = state.get(_batch_key(manifest, batch))
    if isinstance(entry, dict):
        return entry
    legacy = state.get(f"batch_{batch}")
    if isinstance(legacy, dict):
        return legacy
    return None


def _batch_completed_files(manifest: str, batch: int) -> set[str]:
    """Return the set of raw file paths already completed for this batch.

    Status-independent read (D1/F7): any entry carrying ``completed_files``
    (``committing`` / ``partial`` / ``committed`` / ``postcheck_failed``)
    resumes from it.  ``gate_failed`` / ``failed`` entries carry none →
    correctly empty.  Resolution binds to ``manifest`` and falls back to the
    legacy unbound key for backward compatibility."""
    entry = _resolve_batch_entry(_load_state(), manifest, batch)
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
    permanent_failed: int = 0,
) -> tuple[bool, str]:
    """R0-2: decide whether to abort the batch after the generate summary.

    A batch that produced zero pages must not fake-commit ``committed`` (B4).
    The only legitimate ``ok==0`` case is a ``--resume`` re-run where every
    file was already completed in a prior run (then there is nothing left to
    do, and the batch is already recorded as done).

    Params:
      ok        number of files successfully generated
      err       number of files that failed generation (retryable)
      pending   number of files still pending — missing on disk this run
      resume    whether ``--resume`` was given
      completed set of raw paths already completed in a prior run
      skip      number of files skipped as already-completed (resume)
      permanent_failed number of files permanently failed (422, non-retryable)

    Returns ``(abort, reason)``.
    """
    if ok == 0 and err > 0:
        return True, "all files failed"
    if ok == 0 and err == 0:
        if pending:
            return True, "all files missing (empty batch)"
        if permanent_failed:
            # ok==0/err==0/pending==0 且存在 422 永久失败（M-3）：零页产出，
            # 原因如实标注而非泛化的 "empty batch"。
            return True, f"all files permanent-failed (422): {permanent_failed}"
        # ok==0, pending==0 — nothing was generated this run.  The ONLY
        # legitimate zero-page outcome is a --resume re-run where every file
        # was already completed in a prior run.  Any other empty batch
        # (all files --skip-files'd, --count 0, plain empty run) must abort
        # instead of fake-committing 'committed' (B4 / M1).
        if resume and skip and len(completed) >= skip:
            return False, "all files already completed (resume)"
        return True, "empty batch (zero pages generated)"
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
    from src.wiki.storage.page_writer import (
        PageNotFoundError, read_page, page_path_for,
    )

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
        except PageNotFoundError:
            # Listed in index but missing on disk → stale index, treat as free
            continue
        except Exception as exc:
            # C3: any other read failure is a real problem — log it and treat
            # as a blocker instead of silently swallowing it.
            _log(f"  WARN overwrite check: read_page failed for {p.id!r}: {exc}")
            blockers.append(
                f"Page {p.id!r}: on-disk read failed ({exc}) — "
                f"cannot confirm stub status."
            )
            continue

        msg = (
            f"Page {p.id!r} ({ptype}) already exists on disk as "
            f"{existing_type} — would overwrite a non-stub page."
        )
        if allow_overwrite:
            _log(f"  WARN overwrite: {msg}")
        else:
            blockers.append(msg)

    return blockers


def _auto_tag_ugc(pages: list, raw_headers: dict[str, str]) -> int:
    """R3-1 / F2: tag UGC-carrier-derived pages with 素材/ugc + 可信度/ugc.

    Runs AFTER reconcile (never before) — reconcile merges relations/sources
    but NOT tags, so tagging the *final* page set is what keeps merged pages
    correctly tagged.  Extras are pre-existing pages and are NOT back-tagged
    (``pages`` here is ``ReconcileResult.pages``, not ``.extras``).  Stubs
    are exempt.

    Deterministic, zero LLM cost.  Mutates ``pages`` in place; returns the
    number of pages tagged.
    """
    from src.wiki.features.lint import _is_ugc_carrier

    carrier_raws = {
        raw for raw, header in (raw_headers or {}).items()
        if _is_ugc_carrier(header)
    }
    if not carrier_raws:
        return 0

    tagged = 0
    for p in pages:
        if getattr(p, "processing_depth", "") == "stub":
            continue
        if not (set(p.sources or []) & carrier_raws):
            continue
        tags = list(p.tags or [])
        changed = False
        for tag in ("素材/ugc", "可信度/ugc"):
            if tag not in tags:
                tags.append(tag)
                changed = True
        if changed:
            p.tags = tags
            tagged += 1
    return tagged


async def _generate_batch(
    paths,
    provider,
    files: list[str],
    completed_files: set[str],
    skip_files: set[str],
    concurrency: int,
    batch_no: int,
    root: Path,
) -> dict:
    """Generate pages for the batch's pending raw files (Phase 5.2).

    Pure coroutine — every I/O dependency is a parameter and
    ``generate_ingest`` is imported at call time so tests can monkeypatch it.
    Completed (resume) and ``--skip-files`` raw files are dropped before any
    LLM call; missing files are counted but not generated.

    Returns a dict::

        ok / err                 files generated / failed
        missing_count            files not on disk this run
        completed_skip_count     files skipped as already-completed (resume)
        skip_count               files excluded via --skip-files
        pending                  [(idx, raw_rel)] actually generated
        pages / extra            all generated pages / extras
        raw_headers              normalized raw_rel → first-chars header
        file_results             raw_rel → per-file result dict (F5)
    """
    from src.pipeline.ingest import generate_ingest
    from src.utils.path import normalize_source_path

    # C1 (plan 1.9 O3): executor 顶层检查 llm 熔断器 —— OPEN 时暂停整批等待恢复，
    # 禁止无冷却重启打满调用。
    await _await_breaker_recovery()

    all_pages: list = []
    all_extra: list = []
    raw_headers: dict[str, str] = {}
    file_results: dict[str, dict] = {}
    ok = err = 0
    missing_count = 0
    completed_skip_count = 0
    skip_count = 0

    pending: list[tuple[int, str]] = []
    for raw_rel in files:
        if raw_rel in skip_files:
            skip_count += 1
            _log(f"SKIP --skip-files: {raw_rel}")
            continue
        if raw_rel in completed_files:
            completed_skip_count += 1
            _log(f"SKIP completed: {raw_rel}")
            continue
        src = root / raw_rel
        if not src.is_file():
            missing_count += 1
            _log(f"SKIP missing: {raw_rel}")
            continue
        pending.append((len(pending), raw_rel))

    _log(f"generating {len(pending)} file(s) with concurrency={concurrency} "
         f"(skipped {len(files) - len(pending)})")

    t0 = time.monotonic()
    sem = asyncio.Semaphore(concurrency)

    async def _ingest_one(idx: int, raw_rel: str) -> tuple[str, object]:
        async with sem:
            from src.circuit_breaker import get_circuit_breaker
            from src.pipeline.retry import CircuitBreakerOpen, PermanentFailure, RetryExhausted

            src = root / raw_rel
            text = src.read_text(encoding="utf-8", errors="replace")
            task_id = f"b{batch_no}-{Path(raw_rel).stem[:30]}"
            header = _read_raw_header(src)

            pages = extra = meta = None
            last_err = None
            permanent_failed = False
            breaker = get_circuit_breaker(LLM_BREAKER)
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
                except PermanentFailure as exc:
                    # 422 content moderation —— 永久失败：不重试、不记 breaker
                    # 故障（非服务故障），标记 permanent_failed 移出重试。
                    last_err = exc
                    permanent_failed = True
                    break
                except CircuitBreakerOpen as exc:
                    # 熔断器 OPEN：不记故障（已 OPEN），等整批暂停恢复后重试。
                    last_err = exc
                    await _await_breaker_recovery()
                    if attempt >= MAX_RETRIES:
                        break
                except RetryExhausted as exc:
                    # 传输层（provider 包装）已 2/10/30s 退避耗尽：不整批重跑
                    # generate_ingest（否则传输层重试会再次触发），直接记失败。
                    last_err = exc
                    break
                except Exception as exc:
                    last_err = exc
                    if attempt < MAX_RETRIES:
                        await asyncio.sleep(2)

            # C1 (plan 1.9 O3): 按文件结果记一次 breaker（重试不重复计数）。
            if last_err is None:
                breaker.record_success()
            elif not permanent_failed and not isinstance(last_err, CircuitBreakerOpen):
                breaker.record_failure()

            result = {
                "raw_rel": raw_rel,
                "header": header,
                "pages": pages,
                "extra": extra,
                "meta": meta,
                "ok": last_err is None,
                "error": str(last_err) if last_err else None,
                "permanent_failed": permanent_failed,
            }
            return raw_rel, result

    tasks = [_ingest_one(i, r) for i, r in pending]
    gathered = await asyncio.gather(*tasks, return_exceptions=True)

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
        elif result["permanent_failed"]:
            # 422 永久失败：不计入 err（非瞬态、非服务故障），移出重试。
            _log(f"  PERM {raw_rel}: {result['error']}")
        else:
            err += 1
            _log(f"  FAIL {raw_rel}: {result['error']}")

    _log(f"generated ok={ok} err={err} "
         f"permanent_failed={sum(1 for r in file_results.values() if r.get('permanent_failed'))} "
         f"total_pages={len(all_pages)} extras={len(all_extra)} "
         f"elapsed={time.monotonic()-t0:.0f}s")

    return {
        "ok": ok, "err": err,
        "permanent_failed": sum(
            1 for r in file_results.values() if r.get("permanent_failed")),
        "missing_count": missing_count,
        "completed_skip_count": completed_skip_count,
        "skip_count": skip_count,
        "pending": pending,
        "pages": all_pages,
        "extra": all_extra,
        "raw_headers": raw_headers,
        "file_results": file_results,
    }


async def _commit_all(
    paths,
    pages: list,
    extras: list,
    batch_key: str,
    batch_files: list[str],
    root: Path,
    task_id: str,
    *,
    prior_completed: set[str] | None = None,
    gen_failed: list[str] | None = None,
    ok: int = 0,
    err: int = 0,
    file_results: dict | None = None,
) -> tuple[dict, int]:
    """Commit reconciled batch pages grouped by raw file (R2-2).

    Pure coroutine — ``commit_ingest`` / ``read_index`` are imported at call
    time so tests can monkeypatch them.  Ownership of a raw file is decided
    by its SOURCE page: a raw_rel belongs to every SOURCE page whose
    ``sources`` field contains it (D1) — never by ``sources[0]`` (F5).

    ``file_results`` (Phase 3 实测接线)：raw_rel → per-file result dict，
    供 ``_missing_slugs_for`` 提取该 raw 的 ``meta["missing_slugs"]`` 透传
    ``commit_ingest`` → knowledge_gaps.json（1.3 O6）。

    State is persisted atomically after every group commit (status
    ``committing``) so a crash mid-batch resumes at file granularity;
    ``failed_files`` holds only this run's failures (a resume replaces them
    with the retried outcome).  ``prior_completed`` seeds ``completed_files``
    on a resume so already-committed files stay recorded.

    Returns ``(state_entry, exit_code)``:
      0  committed + POSTCHECK clean
      3  POSTCHECK found missing pages (entry carries the ``missing`` ids)
    """
    from src.pipeline.ingest import commit_ingest
    from src.wiki.core.types import PageType
    from src.wiki.features.indexer import read_index
    from src.wiki.storage.page_writer import page_path_for

    def _missing_slugs_for(raw_rel: str) -> list | None:
        """Extract this raw's unresolved references from its generate meta."""
        if not file_results:
            return None
        res = file_results.get(raw_rel)
        if not res:
            return None
        meta = res.get("meta") or {}
        return meta.get("missing_slugs")

    batch_set = set(batch_files)

    # {raw_rel: source_page_id} — SOURCE-page ownership, not sources[0].
    raw_to_source: dict[str, str] = {}
    for p in pages:
        if getattr(p, "type", None) != PageType.SOURCE:
            continue
        for src in (p.sources or []):
            if src in batch_set:
                raw_to_source.setdefault(src, p.id)

    # Group batch pages by their primary raw_rel (first batch source in the
    # page's own sources).  Pages with no batch source are committed as a
    # single orphan group so POSTCHECK still accounts for them.
    groups: dict[str, list] = {}
    group_order: list[str] = []
    orphans: list = []
    for p in pages:
        primary = next((r for r in (p.sources or []) if r in batch_set), None)
        if primary is None:
            orphans.append(p)
            continue
        if primary not in groups:
            groups[primary] = []
            group_order.append(primary)
        groups[primary].append(p)

    completed: list[str] = list(prior_completed or [])
    failed: list[str] = list(gen_failed or [])
    committed_pages = 0
    # Phase 3：记录本批实际写入的页面 id（pages + extras），供验收脚本
    # 用精确批内集合而非 mtime 窗口（多次重跑后窗口口径会混入历史页）。
    batch_page_ids: list[str] = sorted({
        p.id for p in (pages or [])
    } | {p.id for p in (extras or [])})

    def _save_committing() -> None:
        state = _load_state()
        state[batch_key] = {
            "status": "committing",
            "files": batch_files,
            "ok": ok, "err": err,
            "completed_files": completed,
            "failed_files": failed,
            "page_ids": batch_page_ids,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        _save_state(state)

    for raw_rel in group_order:
        spages = groups[raw_rel]
        try:
            await commit_ingest(
                paths, root / raw_rel, spages, task_id=task_id,
                # 1.3 O6：透传本 raw 的未解析引用 → knowledge_gaps.json
                # （Phase 3 实测：此前未传，gap 账本在 batch 路径从未写入，
                # 导致批内断链无法按 F2 语义归入 gap 而非计为 M1 断链）。
                missing_slugs=_missing_slugs_for(raw_rel),
            )
        except Exception as exc:
            failed.append(raw_rel)
            _log(f"  COMMIT FAIL {raw_rel}: {exc}")
        else:
            committed_pages += len(spages)
            # Mark every raw_rel that shares this group's SOURCE page as
            # completed (handles alias entries mapping to the same source).
            src_page_id = raw_to_source.get(raw_rel)
            if src_page_id is not None:
                for rr, sid in raw_to_source.items():
                    if sid == src_page_id and rr not in completed:
                        completed.append(rr)
            elif raw_rel not in completed:
                completed.append(raw_rel)
        _save_committing()

    if orphans:
        _log(f"  COMMIT {len(orphans)} orphan page(s) (no batch source)")
        try:
            await commit_ingest(
                paths, root / "(batch-reconcile)", orphans, task_id=task_id)
        except Exception as exc:
            failed.append("(orphans)")
            _log(f"  COMMIT FAIL (orphans): {exc}")
        _save_committing()

    # ── POSTCHECK (zero LLM cost) ────────────────────────────────────
    _post_errors = 0
    missing: list[str] = []
    _missing_extras = False

    # B9: extras are pre-existing pages touched by reverse relations — one
    # independent audit event, no fake per-file ingest log.
    if extras:
        _log(f"committing {len(extras)} extra page(s) (reverse-relation) ...")
        try:
            await commit_ingest(
                paths, Path("(batch-reconcile)"), [], extras,
                task_id=task_id, event="reverse-relation",
            )
        except Exception as exc:
            # H2: an extras commit failure must not be masked by exit 0 —
            # POSTCHECK only scans batch pages, never extras, so count it
            # here.  End the batch postcheck_failed / exit 3 instead of
            # fake-committing 'committed'.
            _post_errors += 1
            _missing_extras = True
            failed.append("(extras)")
            _log(f"  COMMIT FAIL extras (FATAL): {exc} — extras pages missing, "
                 f"batch must not fake-commit")

    _index_ids = {e[0] for e in read_index(paths)}
    for _p in pages:
        _pp = page_path_for(paths, _p.type, _p.id)
        if not _pp.exists():
            _log(f"POSTCHECK MISSING: {_p.id} — file not on disk")
            _post_errors += 1
            missing.append(_p.id)
        elif _p.id not in _index_ids:
            _log(f"POSTCHECK NOT-IN-INDEX: {_p.id}")
            _post_errors += 1
            missing.append(_p.id)

    if _post_errors:
        _log(f"POSTCHECK: {_post_errors} error(s) — review before next batch")
        entry = {
            "status": "postcheck_failed",
            "files": batch_files,
            "ok": ok, "err": err,
            "completed_files": completed,
            "failed_files": failed,
            "missing": missing,
            "missing_extras": _missing_extras,
            "page_ids": batch_page_ids,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
    else:
        _log("POSTCHECK: all pages on disk and indexed")
        entry = {
            "status": "committed",
            "files": batch_files,
            "ok": ok, "err": err,
            "completed_files": completed,
            "failed_files": failed,
            "page_ids": batch_page_ids,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
    state = _load_state()
    state[batch_key] = entry
    _save_state(state)
    return entry, 3 if _post_errors else 0


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
    ap.add_argument("--skip-files", default="",
                    help="comma-separated raw_rel list to exclude from this batch")
    args = ap.parse_args()

    t_batch = time.monotonic()  # C7: batch-level wall-clock guard

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

    # ── H1: postcheck_failed 批不可 --resume（缺页永不补）────────────
    # A prior run that ended postcheck_failed is NOT resumable: its
    # completed_files already include the files whose pages are missing, so
    # --resume would skip exactly those files, generate nothing, and (B4)
    # fake-commit 'committed' / exit 0 while the missing pages stay missing.
    # Block before any LLM/generate work — only manual repair of the missing
    # pages or a non-resume re-run can clear it.
    batch_key = _batch_key(args.manifest, args.batch)
    if args.resume:
        _prior = _resolve_batch_entry(_load_state(), args.manifest, args.batch)
        if isinstance(_prior, dict) and _prior.get("status") == "postcheck_failed":
            _missing = _prior.get("missing", [])
            _log(f"RESUME BLOCKED: prior run ended postcheck_failed — "
                 f"{len(_missing)} missing page(s): {_missing}")
            _log("先人工修复缺页，或非 --resume 重跑 — resume 会把缺页所属文件当已完成 "
                 "skip 掉，不会补生成")
            _save_state_entry(batch_key, {
                "status": "postcheck_failed",
                "files": files,
                "ok": _prior.get("ok", 0),
                "err": _prior.get("err", 0),
                "missing": _missing,
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            })
            return 1

    from src.pipeline import _get_provider, _resolve_wiki_paths
    from src.wiki.features.batch_reconcile import reconcile_batch
    from src.wiki.features.ndg_gate import run_ndg_gate

    paths = _resolve_wiki_paths(args.project)
    provider = _get_provider(args.project)
    _log(f"provider: {type(provider).__name__}")

    # ── Phase 5.2: generate (concurrent, no writes) ──────────────────
    # Checkpoint resume: skip files already completed in a prior run.
    completed_files: set[str] = set()
    if args.resume:
        completed_files = _batch_completed_files(args.manifest, args.batch)
        if completed_files:
            _log(f"resume: skipping {len(completed_files)} already-completed file(s)")

    skip_files = {s.strip() for s in args.skip_files.split(",") if s.strip()}
    if skip_files:
        _log(f"--skip-files: excluding {len(skip_files)} file(s)")

    gen = await _generate_batch(
        paths=paths, provider=provider, files=files,
        completed_files=completed_files, skip_files=skip_files,
        concurrency=args.concurrency, batch_no=args.batch, root=ROOT,
    )

    abort, reason = _decide_abort(
        ok=gen["ok"], err=gen["err"], pending=gen["missing_count"],
        resume=args.resume, completed=completed_files,
        skip=gen["completed_skip_count"],
        permanent_failed=gen.get("permanent_failed", 0),
    )
    if abort:
        _log(f"BATCH ABORTED: {reason}")
        _save_state_entry(batch_key, {
            "status": "failed",
            "files": files,
            "ok": gen["ok"], "err": gen["err"],
            "permanent_failed": gen.get("permanent_failed", 0),
            "missing": gen["missing_count"],
            "skipped_completed": gen["completed_skip_count"],
            "reason": reason,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        return 1

    # ── Phase 4.2: batch reconcile (R1-2: extras separated) ──────────
    result = reconcile_batch(gen["pages"], gen["extra"], paths=paths)
    if result.stubs_suppressed:
        _log(f"reconcile: suppressed {result.stubs_suppressed} stub(s)")
    for m in result.merged:
        _log(f"reconcile: merged {m.dropped!r} → {m.kept!r} ({m.reason})")
    for c in result.conflicts:
        _log(f"reconcile: CONFLICT {c.slug!r} types={c.types}")

    # ── R3-1 / F2: UGC carrier auto-tag (AFTER reconcile, BEFORE gate) ──
    # reconcile merges relations/sources but not tags; tagging the final page
    # set keeps merged pages correctly tagged.  Extras are pre-existing pages
    # and are intentionally not back-tagged.
    _auto_tagged = _auto_tag_ugc(result.pages, gen["raw_headers"])
    if _auto_tagged:
        _log(f"auto-tag: {_auto_tagged} UGC-carrier-derived page(s) "
             f"tagged 素材/ugc + 可信度/ugc")

    # ── NDG gate (P4b-P7) ────────────────────────────────────────────
    gate_rc = 0
    if not args.skip_gate:
        if result.conflicts:
            _log(f"gate: {len(result.conflicts)} cross-type slug conflict(s) → FAIL")
            gate_rc = 1
        else:
            report = run_ndg_gate(
                result.pages,
                raw_headers=gen["raw_headers"],
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
        _save_state_entry(batch_key, {
            "status": "gate_failed",
            "files": files,
            "ok": gen["ok"], "err": gen["err"],
            "conflicts": [(c.slug, list(c.types)) for c in result.conflicts],
            "merged_count": len(result.merged),
            "stubs_suppressed": result.stubs_suppressed,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        return 2

    # ── B6: overwrite protection (check against existing wiki) ────────
    overwrite_blockers = _check_overwrite_protection(
        result.pages, paths, args.allow_overwrite)
    if overwrite_blockers:
        _log(f"B6 overwrite protection: {len(overwrite_blockers)} blocker(s)")
        for msg in overwrite_blockers:
            _log(f"  BLOCK {msg}")
        _log("BATCH BLOCKED: overwrite protection — use --allow-overwrite to "
             "force, or --skip-files <raw_rel,...> to exclude the source file")
        _save_state_entry(batch_key, {
            "status": "overwrite_blocked",
            "files": files,
            "ok": gen["ok"], "err": gen["err"],
            "overwrite_blockers": overwrite_blockers,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        return 2

    # ── Commit (R2-2): per-file, SOURCE-page ownership, POSTCHECK ─────
    _log(f"committing {len(result.pages)} reconciled page(s) ...")
    _entry, rc = await _commit_all(
        paths=paths,
        pages=result.pages,
        extras=result.extras,
        batch_key=batch_key,
        batch_files=files,
        root=ROOT,
        task_id=f"b{args.batch}",
        prior_completed=completed_files,
        # permanent_failed（422）不属可重投错误：不进 failed_files（M-2）。
        gen_failed=[r for r, res in gen["file_results"].items()
                    if not res["ok"] and not res.get("permanent_failed")],
        ok=gen["ok"], err=gen["err"],
        file_results=gen["file_results"],
    )

    if rc == 0:
        _log(f"BATCH DONE ok={gen['ok']} err={gen['err']} "
             f"pages={len(result.pages)} gate=PASS")
    else:
        _log(f"BATCH DONE WITH ERRORS ok={gen['ok']} err={gen['err']} "
             f"pages={len(result.pages)} → POSTCHECK FAILED (exit {rc})")

    elapsed = time.monotonic() - t_batch
    if elapsed > BATCH_WARN_SECONDS:
        _log(f"WARN: batch took {elapsed:.0f}s (>60min)")
    return rc


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
