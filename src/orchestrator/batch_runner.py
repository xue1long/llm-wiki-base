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
import asyncio
import json
import logging
import os
import subprocess
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

DEFAULT_MANIFEST = ".index/reingest_plan.json"
DEFAULT_CONCURRENCY = 3
MAX_FAIL_STREAK = 3          # B1：连续 3 批失败 → blocklist
CRASH_STAGES = ("generate", "gate", "cascade", "commit")

_logger = logging.getLogger("batch_runner")


# ---------------------------------------------------------------------------
# Test hooks
# ---------------------------------------------------------------------------

def _crash_at(stage: str) -> None:
    """kill -9 注入：env BATCH_EXECUTOR_CRASH_AT 匹配时 os._exit(137)。"""
    target = os.environ.get("BATCH_EXECUTOR_CRASH_AT", "")
    if target == stage:
        _logger.warning("[crash-inject] os._exit(137) at stage %s", stage)
        os._exit(137)


def _snapshot_page_hashes(paths, pages) -> dict[str, str]:
    """Task 0.3：generate 结束时为存量目标页记录 sha256 基线（TOCTOU CAS）。"""
    import hashlib
    from src.wiki.schema_registry import SchemaRegistry
    from src.wiki.storage.page_writer import page_path_for

    registry = SchemaRegistry.from_project(paths.root)
    out: dict[str, str] = {}
    for p in pages:
        try:
            path = page_path_for(
                paths, p.type, p.id, registry,
                getattr(p, "custom_type", "") or "",
            )
            if path.exists():
                out[p.id] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            continue
    return out


def _touch_page_for_toctou(paths, pages) -> None:
    """测试钩子：模拟 generate 与 commit 之间的人工编辑（RUFLO_EXECUTOR_TOUCH_RAW）。"""
    from src.wiki.schema_registry import SchemaRegistry
    from src.wiki.storage.page_writer import page_path_for

    registry = SchemaRegistry.from_project(paths.root)
    for p in pages:
        try:
            path = page_path_for(
                paths, p.type, p.id, registry,
                getattr(p, "custom_type", "") or "",
            )
            if path.exists():
                path.write_text(
                    path.read_text(encoding="utf-8") + "\n<!-- manual edit -->\n",
                    encoding="utf-8",
                )
        except OSError:
            continue


def _fake_generate(raw_rel: str) -> list:
    """离线确定性生成（RUFLO_EXECUTOR_FAKE_GENERATE=1）——测试专用。

    产出 gate-clean 页面：source 页 + concept 页，均带 v2.0.0 模板版本注释
    与全部必填槽标题（bundled 2.0.0 槽集），lint MISSING-SECTION 不误报。
    ``RUFLO_FAKE_PLACEHOLDER=1`` 时 body 带占位符子串（lint ERROR → 门禁失败）；
    ``RUFLO_FAKE_FAIL=1`` 时抛 RuntimeError（failed 状态机路径）。
    """
    from src.wiki.core.types import PageType, WikiPage

    if os.environ.get("RUFLO_FAKE_FAIL") == "1":
        raise RuntimeError("fake generate failure (RUFLO_FAKE_FAIL=1)")

    stem = Path(raw_rel).stem
    ph = " 待补充 " if os.environ.get("RUFLO_FAKE_PLACEHOLDER") == "1" else "内容"
    now = int(time.time() * 1000)
    source_body = (
        "<!-- wiki-template-version: 2.0.0 -->\n<!-- wiki-template-type: source -->\n\n"
        "## 来源元数据\n\n- 路径: `{raw}`\n\n## 摘要\n\n摘要{ph}\n\n"
        "## 关键观点\n\n- 观点\n\n## 抽取的概念\n\n- 概念"
    ).format(raw=raw_rel, ph=ph)
    concept_body = (
        "<!-- wiki-template-version: 2.0.0 -->\n<!-- wiki-template-type: concept -->\n\n"
        "## 定义\n\n定义{ph}\n\n## 主要特点\n\n- 特点\n\n## 例子\n\n- 例\n\n"
        "## 相关概念\n\n[[concept-{stem}]]\n\n## 参考来源\n\n[[src-{stem}]]"
    ).format(stem=stem, ph=ph)
    return [
        WikiPage(
            id=f"src-{stem}", title=f"源{stem}", type=PageType.SOURCE,
            sources=[raw_rel], body=source_body, grade="A",
            processing_depth="source",
            created_at=now, updated_at=now,
        ),
        WikiPage(
            id=f"concept-{stem}", title=f"概念{stem}", type=PageType.CONCEPT,
            sources=[raw_rel], body=concept_body, grade="B",
            processing_depth="concept",
            created_at=now, updated_at=now,
        ),
    ]


def _is_fake_mode() -> bool:
    return os.environ.get("RUFLO_EXECUTOR_FAKE_GENERATE") == "1"


def _estimate_batch_cost(ok: int, err: int) -> float:
    """估算本批费用（USD）。I2 review：真实模式不能恒 0.0。

    - fake 模式：RUFLO_FAKE_COST（默认 0.2 USD/批，测试可控）；
    - 真实模式：按 LLM 调用次数估算（每 raw ≈1 次 generate + 每页合成，
      粗算 ok+err 次 × COST_PER_CALL），COST_PER_CALL 取 OpenAI
      text-embedding/chat 的保守上限。精确计价应接 token 计量（待接入，
      本估算保证 ``--budget-usd`` 在生产有意义而非 no-op）。
    """
    if _is_fake_mode():
        return float(os.environ.get("RUFLO_FAKE_COST", "0.2"))
    # 0.2 B2 定稿预算口径：每 LLM 调用 ~$0.0005 上限（glm-5.2 级别）
    COST_PER_CALL = float(os.environ.get("RUFLO_COST_PER_CALL", "0.0005"))
    return round((ok + err) * COST_PER_CALL, 4)


# ---------------------------------------------------------------------------
# Path / provider resolution
# ---------------------------------------------------------------------------

def _resolve_paths(args) -> WikiPaths:
    if getattr(args, "root", None):
        return WikiPaths(Path(args.root))
    from src.pipeline import _resolve_wiki_paths
    return _resolve_wiki_paths(args.project)


def _resolve_provider(args):
    """按 --project 解析 LLM provider（C1：真实模式不能传 None）。

    --root 测试模式无项目注册 → 返回默认 provider（_get_provider(None)）。
    """
    from src.pipeline import _get_provider
    project_id = getattr(args, "project", None)
    return _get_provider(project_id)


# ---------------------------------------------------------------------------
# Per-batch helpers
# ---------------------------------------------------------------------------

def _git_snapshot(paths: WikiPaths) -> str | None:
    """记录当前 git HEAD（每批前快照，guidance #13）。非 git 仓库返回 None。"""
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


def _is_immutable_source(paths: WikiPaths, raw_rel: str) -> bool:
    """is_immutable 存量 source 页 → True（摄入前跳过，guidance #13）。"""
    from src.services.ingest import probe_source_page
    from src.wiki.storage.page_writer import read_page, page_path_for
    from src.wiki.core.types import PageType

    source_id = probe_source_page(paths, raw_rel)
    if source_id is None:
        return False
    try:
        page = read_page(page_path_for(paths, PageType.SOURCE, source_id))
        return bool(getattr(page, "is_immutable", False))
    except Exception:
        return False


async def _generate_raw(paths, provider, raw_rel, batch_no) -> tuple[list, list, dict]:
    """Phase 1：生成单 raw 页面（dry，零磁盘写）。返回 (pages, extras, meta)。"""
    from src.pipeline.ingest import generate_ingest
    from src.utils.path import normalize_source_path

    src = paths.root / raw_rel
    text = src.read_text(encoding="utf-8", errors="replace")
    task_id = f"b{batch_no}-{Path(raw_rel).stem[:30]}"
    return await generate_ingest(
        paths=paths, source_path=Path(raw_rel), source_text=text,
        provider=provider, task_id=task_id,
    )


async def _commit_raw(paths, raw_rel, pages, extras, batch_key, task_id,
                      meta: dict | None = None) -> str:
    """Phase 3：按分支提交单个 raw。返回分支名（reingest / first_ingest）。

    C2：有 source 页 → reingest（记 pending_deletion → cascade_delete +
    删向量 → commit 新页）；无 → 首摄 commit。cascade 抛 FileNotFoundError
    （源页被删）→ 降级首摄而非 failed。

    向量删除（I3 review）：降级首摄 / pending_deletion 续跑（probe=None）
    分支也必须幂等删除旧向量——崩溃发生在 cascade 与删向量之间时，旧 chunk
    不清理会让搜索命中陈旧内容。delete_by_source 幂等（无残留删 0 行）。

    ``meta``（Phase 4 试跑实测修复 A）：generate 阶段返回的 dict，其中
    ``missing_slugs`` 是本批采集的未解析引用——必须透传给 ``commit_ingest``
    落盘 KnowledgeGapStore（此前丢弃 → gap 账本在 batch 路径从未写入，
    且门禁在 commit 前读不到本批 gap → BROKEN-LINK 误拦整批）。
    """
    from src.services.ingest import probe_source_page
    from src.wiki.features.cascade_delete import cascade_delete
    from src.vector.store import delete_by_source, init_vector_store_for_paths
    from src.pipeline.ingest import commit_ingest

    source_id = probe_source_page(paths, raw_rel)
    branch = "reingest" if source_id is not None else "first_ingest"
    if source_id is not None:
        # 重建调度成功 → 先记 pending_deletion，再删（禁裸窗口）
        set_raw_status(paths, batch_key, raw_rel, "pending_deletion",
                       source_id=source_id)
        try:
            cascade_result = cascade_delete(paths, source_id)
        except FileNotFoundError:
            branch = "first_ingest"   # 源页已被并发删除 → 首摄分支
            cascade_result = {}
        else:
            cascade_result.get("deleted_pages", [])
        init_vector_store_for_paths(paths)
        delete_by_source(paths, raw_rel)
        _crash_at("cascade")
    else:
        # 首摄/续跑分支：仍幂等清旧向量（I3 review）
        init_vector_store_for_paths(paths)
        delete_by_source(paths, raw_rel)
    missing_slugs = (meta or {}).get("missing_slugs")
    await commit_ingest(paths, Path(raw_rel), pages, extras, task_id=task_id,
                        missing_slugs=missing_slugs,
                        expected_page_hashes=(meta or {}).get("expected_page_hashes"))
    set_raw_status(paths, batch_key, raw_rel, "done", branch=branch)
    return branch


def _set_batch_status(paths, batch_key, status: str, **extra) -> None:
    """批级状态写入（H① 锁纪律：所有 batch_build_state 写走统一锁路径）。

    与 set_raw_status 一样经 update_batch_state（文件锁 + os.replace 原子写），
    杜绝并发 executor 的读-改-写丢失更新（review M3）。
    """
    from src.services.batch_state import update_batch_state

    def _mutate(state: dict) -> dict:
        entry = state.setdefault(batch_key, {})
        if not isinstance(entry, dict):
            entry = {}
            state[batch_key] = entry
        entry["status"] = status
        entry["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        for k, v in extra.items():
            entry[k] = v
        return state

    update_batch_state(paths, _mutate)


def _update_fail_streak(paths, batch_key, raw_rel, status) -> None:
    """B1：failed 连续计数；>=3 → blocklist + 告警。"""
    state = load_batch_state(paths)
    entry = state.get(batch_key, {}).get("raw_states", {}).get(raw_rel, {})
    streak = int(entry.get("fail_streak", 0))
    if status == "failed":
        streak += 1
        extra = {"fail_streak": streak}
        if streak >= MAX_FAIL_STREAK:
            extra["blocklisted"] = True
            print(f"ALERT: {raw_rel} failed {streak} consecutive batches — "
                  f"BLOCKLISTED, manual review required", flush=True)
    else:
        streak = 0
        extra = {"fail_streak": 0}
    set_raw_status(paths, batch_key, raw_rel, status, **extra)


def _auto_tag_ugc(pages: list, raw_headers: dict[str, str]) -> int:
    """R3-1 / F2：给 UGC carrier raw 派生页补 ``素材/ugc`` + ``可信度/ugc``。

    与 phase4_batch 的 auto-tag 步骤同语义（Phase 4 试跑实测缺陷 C）：
    pre-commit 门禁的 P4b（NDG）把"UGC 派生页缺 tag"列为 blocker——
    此步骤在门禁前确定性补齐（零 LLM 成本），否则 UGC 语料整批被拦。

    ``pages`` 是本批新产出（不含 extras——extras 是存量 reverse-touch 页，
    不参与批内 tag 判定，修复 B）。stub 豁免。
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


async def _upsert_batch_vectors(paths, pages) -> int:
    """为批内已提交页面切块 + embedding + upsert（guidance #9）。

    复用 ``src.utils.text.chunk_markdown`` + ``src.llm.embedding_runtime``
    provider + ``src.vector.upsert.vector_upsert_chunks``（与 indexer /
    librarian 同一套向量写入路径）。无 embedding provider 时抛错，由调用方
    降级（search degrade，不拦批）。
    """
    from src.utils.text import chunk_markdown
    from src.llm.embedding_runtime import get_embedding_provider
    from src.vector.store import init_vector_store_for_paths
    from src.vector.upsert import vector_upsert_chunks
    from src.types import VectorChunk
    from src.utils.path import normalize_source_path
    from datetime import timezone, datetime

    init_vector_store_for_paths(paths)
    provider = get_embedding_provider()
    total = 0
    for p in pages:
        content = (p.body or "").strip()
        if not content:
            continue
        chunks = chunk_markdown(content)
        if not chunks:
            continue
        embedding_results = await provider.embed(chunks)
        if embedding_results and hasattr(embedding_results[0], "embedding"):
            embeddings = [e.embedding for e in embedding_results]
        else:
            embeddings = list(embedding_results)
        if not embeddings or len(embeddings) != len(chunks):
            continue
        now = int(datetime.now(timezone.utc).timestamp() * 1000)
        lance_chunks = [
            VectorChunk(
                id=f"{p.id}-chunk-{i}",
                task_id=p.id,
                content=chunk,
                embedding=embeddings[i],
                path=normalize_source_path(p.id, paths.root),
                updated_at=now,
            )
            for i, chunk in enumerate(chunks)
        ]
        vector_upsert_chunks(lance_chunks)
        total += len(lance_chunks)
    return total


async def _rerun_gate_batch(paths, batch_key, files,
                            batch_page_ids=None) -> bool:
    """整批门禁复核（C4：崩溃后续跑对整批——含已 done 文件——重跑门禁）。

    从磁盘读取本批实际写入的页面（``batch_page_ids`` 过滤），跑完整的
    NDG + fields/tags/lint/对账 门禁。失败 → 批状态 gate_failed（调用方
    决定是否回滚）。这是门禁作用域收缩的兜底：pre-commit 门禁只管本轮的
    内存页，复核把作用域钉回整批。

    ``batch_page_ids``（Phase 4 试跑实测修复 E）：本批新写页 id。为空时
    退化为旧行为（按 source 关联全扫）——但真实批次必须传入，否则
    reverse-touch 写回的存量 extras（历史非法 relation/旧 tag 属 M8/M9
    消解范围）会被误拦（batch 0 实测：东方玄幻 存量 contrasts → 整批
    gate_recheck_failed）。
    """
    from src.wiki.storage.page_writer import read_page

    if not batch_page_ids:
        return True
    id_set = set(batch_page_ids)
    pages = []
    for sub in (paths.wiki_sources, paths.wiki_entities,
                paths.wiki_concepts, paths.wiki_synthesis):
        if not sub.exists():
            continue
        for f in sub.glob("*.md"):
            try:
                pg = read_page(f)
            except Exception:
                continue
            if pg.id in id_set:
                pages.append(pg)
    if not pages:
        return True
    passed, issues = run_precommit_gate(pages, [], {}, paths,
                                        allow_overwrite=True)
    if not passed:
        for iss in issues[:10]:
            print(f"  [GATE] {iss}", flush=True)
        print(f"  [GATE] {len(issues)} issue(s) — FAIL", flush=True)
    else:
        print(f"  [GATE] {len(pages)} page(s) — PASS", flush=True)
    return passed


# ---------------------------------------------------------------------------
# Batch orchestration entry
# ---------------------------------------------------------------------------

# ── BatchRunner 抽象基类（P1-A 3c）───────────────────────────────────
# 生命周期钩子 _on_phase_start / _on_phase_end 预留崩溃注入测试支持。

@dataclass
class Batch:
    """单批元数据（对应 manifest 中一个 batch 条目）。"""
    batch_no: int
    theme: str = ""
    files: list[str] = field(default_factory=list)


@dataclass
class GateReport:
    """门禁报告。"""
    passed: bool = True
    issues: list[str] = field(default_factory=list)


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
    generated: dict[str, tuple[list, list, dict]] = {}
    raw_headers: dict[str, str] = {}
    failed_raws: list[str] = []
    perm_failed_raws: list[str] = []
    skipped_immutable: list[str] = []

    # 生命周期钩子：generate 阶段开始
    _runner = getattr(args, '_batch_runner', None)
    if _runner is not None:
        _runner._on_phase_start("generate", Batch(batch_no=args.batch, files=pending))

    async def _gen_one(raw_rel: str) -> None:
        set_raw_status(paths, batch_key, raw_rel, "in_progress")
        _crash_at("generate")   # 生成前注入点（测试）
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
                    paths, provider, raw_rel, args.batch)
                # Task 0.3 TOCTOU：generate 结束时为"将要覆盖的存量页"记录
                # content-hash 基线；commit 前若磁盘内容已变化（人工编辑/
                # 并发写）则 WRITE-CONFLICT，不静默覆盖。
                meta = dict(meta or {})
                meta["expected_page_hashes"] = _snapshot_page_hashes(paths, pages)
                generated[raw_rel] = (pages, extras, meta)
            if os.environ.get("RUFLO_EXECUTOR_TOUCH_RAW") == raw_rel:
                # 测试钩子：模拟 generate 与 commit 之间的人工编辑
                _touch_page_for_toctou(paths, pages)
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

    sem = asyncio.Semaphore(args.concurrency)
    async def _gen_locked(raw_rel: str) -> None:
        async with sem:
            await _gen_one(raw_rel)

    await asyncio.gather(*(_gen_locked(r) for r in pending))

    # 生命周期钩子：generate 阶段结束
    if _runner is not None:
        _runner._on_phase_end("generate", Batch(batch_no=args.batch, files=pending), None)

    # B1：failed 连续计数必须先于任何 return 路径（含 abort）落盘，
    # 否则"整批零页"时 blocklist 永不触发（review 实测）。
    for raw in failed_raws:
        _update_fail_streak(paths, batch_key, raw, "failed")
    for raw in perm_failed_raws:
        _update_fail_streak(paths, batch_key, raw, "permanent_failed")

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

    # ── Phase 2：pre-commit 门禁（内存页，失败 = 零写入）────────────
    if _runner is not None:
        _runner._on_phase_start("gate", Batch(batch_no=args.batch, files=pending))
    all_pages = [p for pages, _, _ in generated.values() for p in pages]
    all_extras = [e for _, extras, _ in generated.values() for e in extras]
    # 修复 A：门禁在 commit 前运行，磁盘 gap 不含本批新增 —— 收集本批
    # generate 已采集的 missing_slugs 并入门禁豁免集，避免误拦整批。
    pending_gap_slugs = {
        m["slug"]
        for _, _, meta in generated.values()
        for m in (meta or {}).get("missing_slugs") or []
    }
    # 修复 C（P4b）：UGC carrier 派生页确定性补 tag（门禁前，零 LLM 成本）。
    if not _is_fake_mode():
        _auto_tagged = _auto_tag_ugc(all_pages, raw_headers)
        if _auto_tagged:
            print(f"  [auto-tag] {_auto_tagged} UGC-carrier-derived "
                  f"page(s) tagged 素材/ugc + 可信度/ugc", flush=True)
    # 本批实际写入的**新页** id（pages，不含 extras）——整批复核只查这批。
    # extras 是存量 reverse-touch 页（历史非法 relation/旧英文 tag 属
    # M8/M9 消解范围），pre-commit 已豁免，整批复核必须同口径（修复 E）。
    batch_page_ids = sorted({p.id for p in all_pages})
    # Task 5：整批 source 候选 → Gate 对账的 ResolutionContext
    # （未解析目标多候选 → TARGET-AMBIGUOUS 可诊断）。
    from src.utils.path import canonical_raw_key
    from src.wiki.features.target_resolver import ResolutionContext
    _src_candidates = []
    for raw in pending:
        if raw not in generated:
            continue
        _slug = (generated[raw][2] or {}).get("source_slug")
        if _slug:
            _src_candidates.append(
                (canonical_raw_key(raw, paths.root), _slug, Path(raw).stem))
    _gate_res_ctx = (
        ResolutionContext(source_candidates=tuple(_src_candidates))
        if _src_candidates else None
    )
    gate_ok, gate_issues = run_precommit_gate(
        all_pages, all_extras, raw_headers, paths,
        allow_overwrite=args.allow_overwrite,
        pending_gap_slugs=pending_gap_slugs,
        resolution_context=_gate_res_ctx)
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
            try:
                branch = await _commit_raw(paths, raw, pages, extras, batch_key,
                                           task_id=f"b{args.batch}", meta=meta)
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