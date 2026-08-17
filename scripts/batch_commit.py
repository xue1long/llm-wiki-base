"""batch_commit.py — Phase 4 串行提交阶段（消费 batch_generate 缓存）。

与 ``batch_generate.py`` 配合，将原 ``batch_executor.py`` 的三步拆为：
  1. ``batch_generate.py`` 并行生成多个批次，产物缓存到 ``.index/generated_cache/``
  2. ``batch_commit.py`` 串行消费缓存：pre-commit 门禁 → 写盘 → 整批复核 →
     预算累计

安全保证：
- commit 严格串行，避免 index.md 并发读改写损坏；
- 门禁失败 = 零写入（与 batch_executor 同语义）；
- 已 done 的 raw 跳过，可中断续跑；
- 生成失败的 raw 标记 failed / permanent_failed，不会进入门禁。

用法::

    # 串行提交 batch 3、4、5（缓存必须已由 batch_generate 生成）
    PYTHONPATH=. python scripts/batch_commit.py --root knowledge/novel-wiki \
        --batches 3-5 --budget-usd 0.2

    # 中断后续跑（跳过 done，继续未完成）
    PYTHONPATH=. python scripts/batch_commit.py --root knowledge/novel-wiki \
        --batches 3-5 --budget-usd 0.2 --resume

退出码：
  0  全部提交完成
  1  参数/缓存错误
  2  某批门禁失败（零写入）
  3  整批复核失败（页面已提交，须 rollback_batch）或预算超限暂停
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.services.batch_state import load_batch_state, raw_status  # noqa: E402
from src.wiki.core.paths import WikiPaths  # noqa: E402

from scripts.batch_generate import (  # noqa: E402
    DEFAULT_CACHE_DIR,
    DEFAULT_MANIFEST,
    _page_from_dict,
    load_cache,
)
from src.wiki.features.batch_gate import run_precommit_gate  # noqa: E402
from scripts.batch_executor import (  # noqa: E402
    _auto_tag_ugc,
    _commit_raw,
    _estimate_batch_cost,
    _is_fake_mode,
    _rerun_gate_batch,
    _set_batch_status,
    _update_fail_streak,
    _upsert_batch_vectors,
)


def _resolve_paths(args) -> WikiPaths:
    if getattr(args, "root", None):
        return WikiPaths(Path(args.root))
    from src.pipeline import _resolve_wiki_paths
    return _resolve_wiki_paths(args.project)


def _parse_batches(text: str) -> list[int]:
    """'3,4,5' / '3-5' / '3' → [3,4,5]。"""
    out: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            a, b = int(a), int(b)
            if a > b:
                a, b = b, a
            out.extend(range(a, b + 1))
        else:
            out.append(int(part))
    return sorted(set(out))


def _git_snapshot(paths: WikiPaths) -> str | None:
    """记录当前 git HEAD（每批前快照）。非 git 仓库返回 None。"""
    import subprocess
    try:
        r = subprocess.run(
            ["git", "-C", str(paths.root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return None


def _load_generated_entries(paths, batch_no: int, cache_dir: str) -> tuple[dict, dict | None]:
    """读取缓存并解包。返回 (entries_by_raw, payload)。cache 缺失返回 ({}, None)。"""
    payload = load_cache(paths.root, batch_no, cache_dir)
    if payload is None:
        return {}, None
    entries = {}
    for e in payload.get("files", []):
        raw = e.get("raw")
        if raw:
            entries[raw] = e
    return entries, payload


def _entry_to_generated(entry: dict) -> tuple[list, list, dict, str]:
    """把 cache entry 反序列化为 (pages, extras, meta, raw_header)。"""
    pages = [_page_from_dict(p) for p in entry.get("pages", [])]
    extras = [_page_from_dict(p) for p in entry.get("extras", [])]
    meta = entry.get("meta") or {}
    raw_header = entry.get("raw_header", "")
    return pages, extras, meta, raw_header


async def _commit_one_batch(args, paths, batch: dict) -> int:
    """提交单个批次。返回 batch_executor 兼容退出码。"""
    batch_no = batch["batch_no"]
    files = batch["files"]
    batch_key = f"batch_{batch_no}"
    cache_dir = args.cache_dir
    print(f"commit batch {batch_no} [{batch.get('theme', '?')}]: "
          f"{len(files)} file(s)", flush=True)

    # git 快照
    if not args.no_git_snapshot:
        snapshot = _git_snapshot(paths)
        if snapshot:
            from src.services.batch_state import update_batch_state
            update_batch_state(paths, lambda st: (
                st.setdefault(batch_key, {}).__setitem__("git_snapshot", snapshot),
                st)[1])

    # 预算顶层检查
    state = load_batch_state(paths)
    cumulative = float(state.get("budget", {}).get("cumulative_usd", 0.0))
    if args.budget_usd is not None and cumulative > args.budget_usd:
        print(f"BUDGET PAUSED: cumulative ${cumulative:.2f} > "
              f"${args.budget_usd:.2f} — not starting batch", flush=True)
        _set_batch_status(paths, batch_key, "paused_budget")
        return 3

    entries, payload = _load_generated_entries(paths, batch_no, cache_dir)
    if payload is None:
        print(f"CACHE MISS: batch {batch_no} not generated yet — "
              f"run scripts/batch_generate.py --batches {batch_no} first",
              flush=True)
        return 1

    # ── 状态机：决定每 raw 动作 ─────────────────────────────────────
    generated: dict[str, tuple[list, list, dict, str]] = {}
    raw_headers: dict[str, str] = {}
    failed_raws: list[str] = []
    perm_failed_raws: list[str] = []
    skipped_immutable: list[str] = []
    missing_cache: list[str] = []

    for raw in files:
        st = raw_status(state, batch_key, raw)
        if st == "done":
            print(f"SKIP done: {raw}", flush=True)
            continue
        if st == "permanent_failed":
            print(f"SKIP blocked: {raw}", flush=True)
            continue
        entry = entries.get(raw)
        if entry is None:
            # 没有缓存：保留原 executor 的 failed 重投语义
            if st == "failed" and not args.resume:
                print(f"SKIP failed (use --resume to resubmit): {raw}", flush=True)
            else:
                missing_cache.append(raw)
            continue
        status = entry.get("status")
        if status == "skipped_immutable":
            print(f"SKIP immutable: {raw}", flush=True)
            skipped_immutable.append(raw)
            # 与 batch_executor 一致：immutable 直接标记 done（不写 wiki）
            from src.services.batch_state import set_raw_status
            set_raw_status(paths, batch_key, raw, "done",
                           skipped="immutable", branch="skip")
            continue
        if status in ("failed", "permanent_failed"):
            if status == "permanent_failed":
                perm_failed_raws.append(raw)
            else:
                failed_raws.append(raw)
            print(f"SKIP generated-failed: {raw} — {entry.get('error', status)}",
                  flush=True)
            continue
        if status != "generated":
            missing_cache.append(raw)
            continue
        pages, extras, meta, header = _entry_to_generated(entry)
        generated[raw] = (pages, extras, meta, header)
        raw_headers[raw] = header

    if missing_cache:
        print(f"CACHE INCOMPLETE: {len(missing_cache)} raw(s) missing generated "
              f"cache in batch {batch_no}: {missing_cache[:5]}", flush=True)
        return 1

    # B1：failed 连续计数先于任何 return 路径
    for raw in failed_raws:
        _update_fail_streak(paths, batch_key, raw, "failed")
    for raw in perm_failed_raws:
        _update_fail_streak(paths, batch_key, raw, "permanent_failed")

    # 全部 done / blocked / immutable → 无实际提交工作
    if not generated and not failed_raws and not perm_failed_raws:
        if skipped_immutable:
            _set_batch_status(paths, batch_key, "committed",
                              ok=len(skipped_immutable),
                              skipped_immutable=skipped_immutable)
            print(f"BATCH DONE (all {len(skipped_immutable)} immutable skipped)",
                  flush=True)
        else:
            print("nothing to do — all files done/blocked", flush=True)
        return 0

    if not generated:
        print(f"BATCH ABORTED: zero pages generated "
              f"(failed={len(failed_raws)} perm={len(perm_failed_raws)})",
              flush=True)
        _set_batch_status(paths, batch_key, "failed",
                          err=len(failed_raws),
                          permanent_failed=len(perm_failed_raws))
        return 1

    # ── 门禁先置 pending_gate ───────────────────────────────────────
    _set_batch_status(paths, batch_key, "pending_gate")

    # ── Phase 2：pre-commit 门禁（内存页，失败 = 零写入）────────────
    all_pages = [p for pages, _, _, _ in generated.values() for p in pages]
    all_extras = [e for _, extras, _, _ in generated.values() for e in extras]
    pending_gap_slugs = {
        m["slug"]
        for _, _, meta, _ in generated.values()
        for m in (meta or {}).get("missing_slugs") or []
    }
    if not _is_fake_mode():
        tagged = _auto_tag_ugc(all_pages, raw_headers)
        if tagged:
            print(f"  [auto-tag] {tagged} UGC-carrier-derived "
                  f"page(s) tagged 素材/ugc + 可信度/ugc", flush=True)
    batch_page_ids = sorted({p.id for p in all_pages})
    gate_ok, gate_issues = run_precommit_gate(
        all_pages, all_extras, raw_headers, paths,
        allow_overwrite=args.allow_overwrite,
        pending_gap_slugs=pending_gap_slugs)
    if not gate_ok:
        print(f"BATCH BLOCKED: pre-commit gate failed — zero wiki writes "
              f"({len(gate_issues)} issue(s))", flush=True)
        for iss in gate_issues[:10]:
            print(f"  [GATE] {iss}", flush=True)
        _set_batch_status(paths, batch_key, "gate_failed",
                          gate_issues=gate_issues[:50])
        for raw in generated:
            _update_fail_streak(paths, batch_key, raw, "failed")
        return 2

    # ── Phase 3：commit（串行）──────────────────────────────────────
    ok = err = perm = 0
    committed_page_ids: list[str] = []
    committed_raws: list[str] = []
    for raw in files:
        if raw not in generated:
            continue
        pages, extras, meta, _ = generated[raw]
        try:
            branch = await _commit_raw(paths, raw, pages, extras, batch_key,
                                       task_id=f"b{batch_no}", meta=meta)
            ok += 1
            committed_page_ids.extend(p.id for p in pages)
            committed_raws.append(raw)
            _update_fail_streak(paths, batch_key, raw, "done")
        except Exception as exc:
            from src.pipeline.retry import PermanentFailure
            if isinstance(exc, PermanentFailure):
                perm += 1
            else:
                err += 1
            print(f"  COMMIT FAIL {raw}: {exc}", flush=True)
    for raw in failed_raws:
        err += 1
    for raw in perm_failed_raws:
        perm += 1

    if committed_raws or committed_page_ids:
        from src.services.batch_state import update_batch_state

        def _record_committed(state: dict) -> dict:
            entry = state.setdefault(batch_key, {})
            entry["completed_files"] = sorted(
                set(entry.get("completed_files", [])) | set(committed_raws))
            entry["page_ids"] = sorted(
                set(entry.get("page_ids", [])) | set(committed_page_ids))
            return state

        update_batch_state(paths, _record_committed)

    # 每批向量 upsert（best-effort）
    if not _is_fake_mode() and generated:
        try:
            upserted = await _upsert_batch_vectors(paths, all_pages)
            print(f"  [vector] upserted {upserted} chunk(s)", flush=True)
        except Exception as exc:
            print(f"  [vector] WARN upsert failed (search degrade): {exc}",
                  flush=True)

    # 整批门禁复核
    state_now = load_batch_state(paths)
    persisted_ids = state_now.get(batch_key, {}).get("page_ids", []) or []
    recheck_ids = sorted(set(persisted_ids) | set(batch_page_ids))
    whole_ok = await _rerun_gate_batch(paths, batch_key, files,
                                       batch_page_ids=recheck_ids)

    # 预算累计 + 批状态
    state = load_batch_state(paths)
    cost = _estimate_batch_cost(ok, err)
    budget_state = state.setdefault("budget", {})
    budget_state["cumulative_usd"] = cumulative + cost
    budget_state["last_batch_usd"] = cost
    from src.services.batch_state import update_batch_state
    if not whole_ok:
        _set_batch_status(paths, batch_key, "gate_recheck_failed",
                          committed=True, ok=ok, err=err)
        update_batch_state(paths, lambda st: (
            st.setdefault("budget", {}).__setitem__("cumulative_usd", cumulative + cost),
            st)[1])
        print("BATCH GATE RE-CHECK FAILED (whole-batch scope, pages already "
              "committed) — use scripts/rollback_batch.py to revert", flush=True)
        return 3
    if args.budget_usd is not None and budget_state["cumulative_usd"] > args.budget_usd:
        _set_batch_status(paths, batch_key, "paused_budget",
                          ok=ok, err=err, permanent_failed=perm)
        update_batch_state(paths, lambda st: (
            st.setdefault("budget", {}).__setitem__("cumulative_usd", cumulative + cost),
            st)[1])
        print(f"BUDGET PAUSED: cumulative ${budget_state['cumulative_usd']:.2f} "
              f"> ${args.budget_usd:.2f}", flush=True)
        return 3
    _set_batch_status(paths, batch_key, "committed",
                      ok=ok, err=err, permanent_failed=perm)
    update_batch_state(paths, lambda st: (
        st.setdefault("budget", {}).__setitem__("cumulative_usd", cumulative + cost),
        st)[1])
    print(f"BATCH DONE ok={ok} err={err} permanent_failed={perm}", flush=True)
    return 0


async def _run_commit(args) -> int:
    paths = _resolve_paths(args)
    manifest = Path(args.manifest)
    if not manifest.is_absolute():
        manifest = paths.root / manifest
    if not manifest.exists():
        print(f"manifest missing: {manifest}", flush=True)
        return 1
    data = json.loads(manifest.read_text(encoding="utf-8"))
    batches = {b["batch_no"]: b for b in data["batches"]}
    targets = _parse_batches(args.batches)
    missing = [n for n in targets if n not in batches]
    if missing:
        print(f"batches not found: {missing}", flush=True)
        return 1

    worst = 0
    for n in targets:
        code = await _commit_one_batch(args, paths, batches[n])
        if code != 0:
            worst = code if worst == 0 else max(worst, code)
            # 门禁失败/复核失败/预算暂停后继续尝试后续批没有意义，暂停。
            if code in (2, 3):
                print(f"STOP after batch {n} (exit {code})", flush=True)
                break
    return worst


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Phase 4 串行提交（消费 generate 缓存）")
    ap.add_argument("--root", default=None, help="project root")
    ap.add_argument("--project", default=None, help="project id (registry)")
    ap.add_argument("--manifest", default=DEFAULT_MANIFEST)
    ap.add_argument("--batches", required=True,
                    help="batch numbers, e.g. 3,4,5 or 3-5")
    ap.add_argument("--budget-usd", type=float, default=None,
                    help="累计费用预算，超限自动暂停")
    ap.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR,
                    help="cache directory under project root")
    ap.add_argument("--allow-overwrite", action="store_true")
    ap.add_argument("--resume", action="store_true",
                    help="续跑：跳过 done，继续处理未完成 raw")
    ap.add_argument("--no-git-snapshot", action="store_true")
    args = ap.parse_args(argv)

    if not args.project and not args.root:
        print("ERROR: provide --project <id> or --root <path>", flush=True)
        return 1
    if args.budget_usd is not None and args.budget_usd <= 0:
        print("ERROR: --budget-usd must be > 0", flush=True)
        return 1
    if not _parse_batches(args.batches):
        print("ERROR: --batches must specify at least one batch", flush=True)
        return 1
    return asyncio.run(_run_commit(args))


if __name__ == "__main__":
    sys.exit(main())
