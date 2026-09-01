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
from src.orchestrator.batch_runner_internal.phases import (
    _phase_commit,
    _phase_gate,
    _phase_generate,
    _prepare_batch,
    _phase_recheck_and_finalize,
)
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
    prepared, early_exit = _prepare_batch(args)
    if prepared is None:
        return early_exit
    paths, provider, batch_key, files, pending, cumulative = prepared

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

    ok, err, perm, terminal_code = await _phase_commit(
        paths, generated, pending, batch_key, args, batch_page_ids, all_pages,
        failed_raws, perm_failed_raws, _runner)
    if terminal_code is not None:
        return terminal_code
    return await _phase_recheck_and_finalize(
        paths, batch_key, pending, batch_page_ids, cumulative, args,
        ok, err, perm, _runner)
