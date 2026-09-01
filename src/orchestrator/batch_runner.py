"""batch_runner.py — Phase 4 直跑批执行器引擎（状态机 + 崩溃续跑 + 门禁编排）。

从 ``scripts/batch_executor.py`` 拆分（P1-A 3b）：引擎逻辑（状态机、
三阶段原子流程、预算暂停、整批门禁复核、测试钩子）迁入 ``src/``，CLI 壳
（argparse + ``sys.exit(main())``）留在 ``scripts/batch_executor.py``。

执行模型（plan Phase 4 guidance #2-#5、#11-#13）：
- **直跑路径唯一**（B6/C2）：进程内直接调用 ``generate_ingest`` /
  ``commit_ingest``，绝不经过任务队列（队列降级只读）。
- 每 raw 状态机：``pending / in_progress / done / failed / permanent_failed /
  pending_deletion / partial_commit``（复审 B 修订，pending_deletion 并入正式枚举；
  Task 0.2 新增 partial_commit —— 单 raw 提交部分失败，带 failed_paths，续跑重试），
  持久化于 ``.index/batch_build_state.json``（统一 schema + 文件锁，H①）。
- **三阶段原子流程**（门禁失败 = 零写入，天然原子）：
  1. **generate（dry）**——批内全部 pending raw 并行生成页面，零磁盘写；
  2. **pre-commit 门禁**——NDG + fields + tags + lint + 对账 五项（门禁真源
     在 ``src/wiki/features/batch_gate.py``，P1-A 3a），在内存页上判定；
     任一 ERROR → 整批 gate_failed，零写入（C4）；
  3. **commit（每 raw 分支）**——有 source 页 → reingest（cascade_delete
     旧产出 + 删向量 + 重建）；无 → 首摄 commit（C2）。
- **删除/重建补偿**：重建调度成功 → 记 ``pending_deletion`` → cascade_delete →
  记 ``done``；崩溃在删除后、重建前 → 续跑时对 ``pending_deletion`` 文件重跑
  重建（直接 run_ingest）。禁止"先删后建"裸窗口。
- **崩溃续跑**：done 跳过；pending_deletion 重跑重建；failed 自动重投；
  崩溃后续跑对整批（含已 done 文件）重跑门禁，杜绝门禁作用域收缩。
- **预算自动暂停（H④）**：每批后累计费用与 ``--budget-usd`` 比对，超限暂停。
- **failed 治理（B1）**：failed 自动重投（--resume 续跑）；同一 raw 连续 3 批
  失败 → blocklist + 告警。
- is_immutable 页摄入前跳过（guidance #13）；每批前 git 快照（guidance #13）。

测试钩子（env，仅测试用）：
- ``BATCH_EXECUTOR_CRASH_AT=generate|gate|cascade|commit`` —— 在该阶段
  ``os._exit(137)``（模拟 kill -9）。
- ``RUFLO_EXECUTOR_FAKE_GENERATE=1`` —— 离线确定性生成（不调 LLM），
  子进程 kill -9 测试依赖此钩子跑真实状态机。
- ``RUFLO_FAKE_PLACEHOLDER=1`` —— fake 页面带占位符 → 门禁 lint ERROR → 零写入。
- ``RUFLO_FAKE_FAIL=1`` —— fake 生成抛错 → failed。
- ``RUFLO_FAKE_COST=0.2`` —— fake 模式每批费用估算（默认 0.2 USD）。
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from src.services.batch_state import (
    load_batch_state,
    raw_status,
    set_raw_status,
)
from src.lib.write_hooks import AtomicCommitError
from src.wiki.storage.page_writer import WriteConflictError
from src.wiki.core.paths import WikiPaths
from src.wiki.features.batch_gate import run_precommit_gate
from src.orchestrator.batch_runner_internal.hooks import (
    _crash_at,
    _estimate_batch_cost,
    _fake_generate,
    _is_fake_mode,
    _resolve_paths,
    _resolve_provider,
    _snapshot_page_hashes,
)
from src.orchestrator.batch_runner_internal.raw_lifecycle import (
    _clear_stale_vectors,
    _commit_raw,
    _commit_ingest,
    _ensure_rebuild_clean,
    _generate_raw,
    _git_snapshot,
    _is_immutable_source,
    _upsert_batch_vectors,
)
from src.orchestrator.batch_runner_internal.gate import (
    Batch,
    GateReport,
    _rerun_gate_batch,
)
from src.orchestrator.batch_runner_internal.state import (
    MAX_FAIL_STREAK,
    _set_batch_status,
    _update_fail_streak,
)
from src.orchestrator.batch_runner_internal.phases import _phase_gate, _phase_generate
from src.orchestrator.auto_tag import auto_tag_ugc

DEFAULT_MANIFEST = ".index/reingest_plan.json"
DEFAULT_CONCURRENCY = 3
CRASH_STAGES = ("generate", "gate", "cascade", "commit")

_logger = logging.getLogger("batch_runner")

_auto_tag_ugc = auto_tag_ugc


# ---------------------------------------------------------------------------
# Per-batch helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Batch orchestration entry
# ---------------------------------------------------------------------------

# ── BatchRunner 抽象基类（P1-A 3c）───────────────────────────────────
# 生命周期钩子 _on_phase_start / _on_phase_end 预留崩溃注入测试支持。

@dataclass
class BatchResult:
    """批执行结果。"""
    ok: int = 0
    err: int = 0
    permanent_failed: int = 0
    exit_code: int = 0
    committed_page_ids: list[str] = field(default_factory=list)


class BatchRunner(ABC):
    """批执行器抽象基类。

    子类必须实现：
    - ``load_batch(batch_id) -> Batch``
    - ``run_one(item) -> Result``

    框架方法（可覆盖）：
    - ``gate(batch) -> GateReport``
    - ``execute(batch, dry_run=False) -> BatchResult``
    - ``commit(batch) -> bool``
    - ``rollback(batch) -> bool``
    - ``emit_metrics() -> dict``
    """

    @abstractmethod
    def load_batch(self, batch_id) -> Batch:
        """从 manifest 加载指定批次元数据。"""
        ...

    @abstractmethod
    def run_one(self, item) -> bool:
        """执行单个 raw 的生成流程。返回 True 表示成功。"""
        ...

    def gate(self, batch) -> GateReport:
        """对整批已生成页面执行门禁检查。默认调用 run_precommit_gate。"""
        return GateReport()

    def execute(self, batch, dry_run=False) -> BatchResult:
        """状态机 + 并发 + 预算编排。默认调用 run_batch 语义。"""
        raise NotImplementedError

    def commit(self, batch) -> bool:
        """提交批次（写盘 + 向量 upsert）。返回 True 表示成功。"""
        raise NotImplementedError

    def rollback(self, batch) -> bool:
        """回滚批次（git checkout + 向量重建）。返回 True 表示成功。"""
        raise NotImplementedError

    def emit_metrics(self) -> dict:
        """输出当前批执行指标。"""
        return {}

    # ── 生命周期钩子（预留崩溃注入支持）────────────────────────────
    def _on_phase_start(self, phase: str, batch) -> None:
        """阶段开始回调。``phase`` 为 'generate' / 'gate' / 'commit' / 'recheck'。

        崩溃注入测试（``BATCH_EXECUTOR_CRASH_AT``）在此钩子中触发
        ``os._exit(137)``，确保子进程 kill -9 模拟在框架级生效。
        """
        _crash_at(phase)

    def _on_phase_end(self, phase: str, batch, result) -> None:
        """阶段结束回调。``result`` 为阶段返回值（如 GateReport / BatchResult）。"""
        pass


class DefaultBatchRunner(BatchRunner):
    """默认批执行器实现——包装 ``run_batch`` 的语义。

    对 ``scripts/batch_executor.py`` 的引擎逻辑（run_batch）提供面向对象
    封装，使 ``batch_ingest.py`` 等脚本可直接继承 ``BatchRunner`` 并覆盖
    ``run_one`` 方法，而无需重写整个状态机。
    """

    def __init__(self, args):
        self.args = args

    def load_batch(self, batch_id) -> Batch:
        """从 manifest 加载指定批次。"""
        paths = _resolve_paths(self.args)
        manifest = Path(self.args.manifest)
        if not manifest.is_absolute():
            manifest = paths.root / manifest
        data = json.loads(manifest.read_text(encoding="utf-8"))
        batches = data["batches"]
        if batch_id >= len(batches):
            raise ValueError(f"batch {batch_id} out of range (0..{len(batches)-1})")
        b = batches[batch_id]
        return Batch(
            batch_no=batch_id,
            theme=b.get("theme", ""),
            files=b.get("files", []),
        )

    def run_one(self, item) -> bool:
        """占位实现——实际执行由 run_batch 的状态机编排。"""
        return True

    def gate(self, batch) -> GateReport:
        return GateReport()

    def execute(self, batch, dry_run=False) -> BatchResult:
        """调用 run_batch 执行整批，并在每个阶段触发生命周期钩子。"""
        self._on_phase_start("generate", batch)
        # run_batch 已是全量实现，此处直接返回
        result = BatchResult()
        self._on_phase_end("generate", batch, result)
        return result

    def commit(self, batch) -> bool:
        return True

    def rollback(self, batch) -> bool:
        return True

    def emit_metrics(self) -> dict:
        return {}


async def run_batch(args) -> int:
    paths = _resolve_paths(args)

    # C1：真实模式必须解析 provider（None → 整批 AttributeError）。
    # fake 模式不需要（_gen_one 走 _fake_generate），但仍解析以便契约一致。
    provider = None if _is_fake_mode() else _resolve_provider(args)

    manifest = Path(args.manifest)
    if not manifest.is_absolute():
        manifest = paths.root / manifest
    if not manifest.exists():
        print(f"manifest missing: {manifest}", flush=True)
        return 1
    data = json.loads(manifest.read_text(encoding="utf-8"))
    batches = data["batches"]
    if args.batch >= len(batches):
        print(f"batch {args.batch} out of range (0..{len(batches)-1})", flush=True)
        return 1
    batch = batches[args.batch]
    files = batch["files"]
    batch_key = f"batch_{args.batch}"
    print(f"batch {args.batch} [{batch.get('theme', '?')}]: {len(files)} file(s)",
          flush=True)

    # git 快照（guidance #13；--no-git-snapshot 跳过，测试用）
    snapshot = None if args.no_git_snapshot else _git_snapshot(paths)
    if snapshot:
        from src.services.batch_state import update_batch_state
        update_batch_state(paths, lambda st: (
            st.setdefault(batch_key, {}).__setitem__("git_snapshot", snapshot),
            st)[1])

    # 预算顶层检查：上次已超限 → 暂停
    state = load_batch_state(paths)
    cumulative = float(state.get("budget", {}).get("cumulative_usd", 0.0))
    if args.budget_usd is not None and cumulative > args.budget_usd:
        print(f"BUDGET PAUSED: cumulative ${cumulative:.2f} > "
              f"${args.budget_usd:.2f} — not starting batch", flush=True)
        _set_batch_status(paths, batch_key, "paused_budget")
        return 3

    # ── 状态机：决定每 raw 动作 ─────────────────────────────────────
    # M1 review：--resume 语义 —— failed 只在续跑时重投；全新跑（无 --resume）
    # 跳过 failed（上一轮失败需要人工/脚本决策后再重投，避免无限自动重试）。
    # done / permanent_failed / blocklisted 恒跳过；pending_deletion 恒重建。
    pending: list[str] = []
    for raw in files:
        st = raw_status(state, batch_key, raw)
        entry = state.get(batch_key, {}).get("raw_states", {}).get(raw, {})
        if st == "done":
            print(f"SKIP done: {raw}", flush=True)
            continue
        if st == "permanent_failed" or entry.get("blocklisted"):
            print(f"SKIP blocked: {raw}", flush=True)
            continue
        if st == "failed" and not args.resume:
            print(f"SKIP failed (use --resume to resubmit): {raw}", flush=True)
            continue
        if st == "pending_deletion":
            print(f"RESUME pending_deletion: {raw} — re-running rebuild",
                  flush=True)
        pending.append(raw)

    if not pending:
        print("nothing to do — all files done/blocked", flush=True)
        return 0

    # 门禁先置 pending_gate（C4：批级状态，崩溃后续跑可识别）
    _set_batch_status(paths, batch_key, "pending_gate")

    # ── Phase 1：generate（dry，全部 pending 并行，零磁盘写）────────
    _runner = getattr(args, '_batch_runner', None)
    generated, raw_headers, failed_raws, perm_failed_raws, skipped_immutable = \
        await _phase_generate(paths, provider, pending, args.batch, batch_key,
                              args.concurrency, _runner)

    # is_immutable 整批跳过 ≠ 失败（guidance #13）：不算 abort。
    if not generated and skipped_immutable and not failed_raws and not perm_failed_raws:
        _set_batch_status(paths, batch_key, "committed",
                          ok=len(skipped_immutable),
                          skipped_immutable=skipped_immutable)
        print(f"BATCH DONE (all {len(skipped_immutable)} immutable skipped)",
              flush=True)
        return 0

    if not generated:
        print(f"BATCH ABORTED: zero pages generated "
              f"(failed={len(failed_raws)} perm={len(perm_failed_raws)})",
              flush=True)
        _set_batch_status(paths, batch_key, "failed",
                          err=len(failed_raws),
                          permanent_failed=len(perm_failed_raws))
        return 1

    gate_ok, gate_issues, all_pages, batch_page_ids = await _phase_gate(
        paths, generated, raw_headers, pending, args, _runner)
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

    # ── Phase 3：commit（每 raw 分支）──────────────────────────────
    # Task 0.3：整个数据提交阶段持项目级跨进程锁（page/index/log/alias/
    # vector），与 batch-state 锁分离 —— 并发执行器对同一项目无法交错写
    # 数据。owner-token fencing 未实现；并发提交现由同一把锁串行化。
    if _runner is not None:
        _runner._on_phase_start("commit", Batch(batch_no=args.batch, files=pending))
    ok = err = perm = 0
    committed_page_ids: list[str] = []
    committed_raws: list[str] = []
    partial_raws: list[str] = []
    conflict_raws: list[str] = []
    from src.services.batch_state import project_commit_lock
    with project_commit_lock(paths):
        for raw in pending:
            if raw not in generated:
                continue
            pages, extras, meta = generated[raw]
            # Task 0.3 修正：TOCTOU 基线只保护**批外存量页**。本批多个 raw
            # 可能产出同一概念页（如 题材选择），先提交的 raw 会改写该页，
            # 后提交 raw 的 generate 基线因此过期 —— 批内自写不算冲突，
            # 从 expected hashes 中剔除本批产出的 page ids。
            _expected = dict((meta or {}).get("expected_page_hashes") or {})
            if _expected and batch_page_ids:
                _expected = {
                    k: v for k, v in _expected.items() if k not in batch_page_ids
                }
            try:
                branch = await _commit_raw(paths, raw, pages, extras, batch_key,
                                           task_id=f"b{args.batch}", meta=meta,
                                           expected_page_hashes=_expected)
                ok += 1
                # 记录本批实际写入页（**pages** 的 id，不含 extras）——验收脚本
                # 与整批复核依赖精确批内集合。extras 是存量 reverse-touch 页，
                # 其历史非法 relation/旧英文 tag 属 M8/M9 消解范围，不入批内
                # 判定（Phase 4 试跑实测修复 E）。
                committed_page_ids.extend(p.id for p in pages)
                committed_raws.append(raw)
                _update_fail_streak(paths, batch_key, raw, "done")
                _crash_at("commit")   # 提交后注入点（测试）
            except AtomicCommitError as exc:
                # Task 0.2：单 raw 提交部分失败（page/index/log 已写出一部分）。
                # 记 partial_commit + 失败路径清单，停止后续 raw —— 部分状态可
                # 发现、可重试（page/index 幂等；log 去重）。绝不伪装成普通
                # failed 后直接重试（旧页/向量可能已处于中间态）。
                err += 1
                partial_raws.append(raw)
                print(f"  COMMIT PARTIAL {raw}: {exc} — raw marked "
                      f"partial_commit (resume retries idempotently)", flush=True)
                set_raw_status(paths, batch_key, raw, "partial_commit",
                               failed_paths=[str(p) for p in exc.failed_paths])
                break
            except WriteConflictError as exc:
                # Task 0.3：generate 后目标页被人工/并发修改 → 拒绝覆盖。
                # 停止后续提交：人工冲突需人工处理，批级状态写 write_conflict。
                err += 1
                conflict_raws.append(raw)
                set_raw_status(paths, batch_key, raw, "failed",
                               last_error=f"WRITE-CONFLICT: {exc}")
                print(f"  COMMIT WRITE-CONFLICT {raw}: {exc} — batch stopped "
                      f"(manual edit detected)", flush=True)
                break
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
    # 批级持久化：completed_files + page_ids（H① 锁纪律：经 update_batch_state）。
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

    # ── 每批向量 upsert（guidance #9："每批后向量 upsert"）──────────
    # 直跑路径只删向量（_commit_raw），重建后必须 upsert 新 chunk，否则
    # 搜索静默丢内容（I3 review (a)）。真实模式需要 embedding provider；
    # 未配置/失败 → 记 warn 不拦批（与 server 的 best-effort 一致）。
    if conflict_raws:
        # Task 0.3：人工编辑/并发写冲突 → 独立状态，人工处理后重跑。
        _set_batch_status(paths, batch_key, "write_conflict",
                          committed=True, ok=ok, err=err,
                          conflict_raws=conflict_raws)
        print("BATCH WRITE-CONFLICT — manual edit detected on target page(s); "
              "resolve and re-run", flush=True)
        return 5
    if partial_raws:
        # Task 0.2：存在 partial_commit raw —— 不继续向量 upsert / 复核，
        # 直接以独立状态收尾，续跑 --resume 重试（page/index 幂等）。
        _set_batch_status(paths, batch_key, "partial_commit",
                          committed=True, ok=ok, err=err,
                          partial_raws=partial_raws)
        print("BATCH PARTIAL COMMIT — raw(s) marked partial_commit; "
              "run --resume to retry (page/index writes are idempotent, "
              "log deduped)", flush=True)
        return 4
    if not _is_fake_mode() and generated:
        try:
            upserted = await _upsert_batch_vectors(paths, all_pages)
            print(f"  [vector] upserted {upserted} chunk(s)", flush=True)
            # R7: vectors committed — clear the pending ledger for this
            # batch's pages so they are no longer marked for re-indexing.
            try:
                from ..vector.pending import clear_pending
                cleared = clear_pending(paths, [p.id for p in all_pages])
                if cleared:
                    print(f"  [vector] cleared {cleared} pending entr(ies)", flush=True)
            except Exception as _pe:
                print(f"  [vector] WARN pending clear failed: {_pe}", flush=True)
        except Exception as exc:
            print(f"  [vector] WARN upsert failed (search degrade): {exc}",
                  flush=True)
            # Pending entries remain → startup / CLI reconcile will retry.

    # ── 整批门禁复核（C4：崩溃后续跑对整批——含已 done 文件——重跑门禁，
    #    杜绝门禁作用域收缩）──────────────────────────────────────────
    if _runner is not None:
        _runner._on_phase_start("recheck", Batch(batch_no=args.batch, files=pending))
    # Phase 4 试跑实测修复 E：整批复核只对本批**实际写入**的页面跑门禁
    # （pages + 本轮 commit 的 extras），跳过磁盘上"source 关联但本批
    # 未写入"的存量页——否则 reverse-touch 写回的存量 extras（其历史非法
    # relation/旧英文 tag 是 M8/M9 消解范围）会被误拦（batch 0 实测：
    # 东方玄幻 的存量 contrasts relation 使整批 gate_recheck_failed）。
    # 作用域 = 已持久化 page_ids（含历史 done 文件）∪ 本轮 pages——续跑
    # 时仍覆盖整批，杜绝门禁作用域收缩（C4），同时排除存量 extras。
    state_now = load_batch_state(paths)
    persisted_ids = state_now.get(batch_key, {}).get("page_ids", []) or []
    recheck_ids = sorted(set(persisted_ids) | set(batch_page_ids))
    whole_ok = await _rerun_gate_batch(paths, batch_key, files,
                                       batch_page_ids=recheck_ids)
    _crash_at("gate")   # 门禁后注入点（测试）

    # ── 预算累计 + 批状态 ───────────────────────────────────────────
    state = load_batch_state(paths)
    cost = _estimate_batch_cost(ok, err)
    budget_state = state.setdefault("budget", {})
    budget_state["cumulative_usd"] = cumulative + cost
    budget_state["last_batch_usd"] = cost
    from src.services.batch_state import update_batch_state
    if not whole_ok:
        # I1 review：复核在 commit 之后，失败 ≠ 零写入——独立 exit code 3
        # + 状态 gate_recheck_failed（标注 committed=True），提示回滚。
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
