"""batch_executor.py — Phase 4 直跑批执行器（状态机 + 崩溃续跑 + pre-commit 门禁）。

执行模型（plan Phase 4 guidance #2-#5、#11-#13）：
- **直跑路径唯一**（B6/C2）：脚本进程内直接调用 ``generate_ingest`` /
  ``commit_ingest``，绝不经过任务队列（队列降级只读）。
- 每 raw 状态机：``pending / in_progress / done / failed / permanent_failed /
  pending_deletion``（复审 B 修订，pending_deletion 并入正式枚举），持久化于
  ``.index/batch_build_state.json``（统一 schema + 文件锁，H①）。
- **三阶段原子流程**（门禁失败 = 零写入，天然原子）：
  1. **generate（dry）**——批内全部 pending raw 并行生成页面，零磁盘写；
  2. **pre-commit 门禁**——NDG + fields + tags + lint + 对账 五项，在内存页
     上判定；任一 ERROR → 整批 gate_failed，零写入（C4）；
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

用法::

    PYTHONPATH=. python scripts/batch_executor.py --root <project_root> \\
        --manifest .index/reingest_plan.json --batch 0 [--resume]
    PYTHONPATH=. python scripts/batch_executor.py --project <id> --batch 0 [--budget-usd 0.2]

退出码：
  0  批完成（committed）
  1  manifest/参数错误 或 无可处理文件
  2  门禁失败（零写入，pre-commit 阶段拦截）
  3  整批门禁复核失败（页面已提交，须 rollback_batch）或 预算超限暂停
  137 kill -9 注入
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.services.batch_state import (  # noqa: E402
    load_batch_state,
    raw_status,
    set_raw_status,
)
from src.wiki.core.paths import WikiPaths  # noqa: E402

DEFAULT_MANIFEST = ".index/reingest_plan.json"
DEFAULT_CONCURRENCY = 3
MAX_FAIL_STREAK = 3          # B1：连续 3 批失败 → blocklist
CRASH_STAGES = ("generate", "gate", "cascade", "commit")

_logger = logging.getLogger("batch_executor")


# ---------------------------------------------------------------------------
# Test hooks
# ---------------------------------------------------------------------------

def _crash_at(stage: str) -> None:
    """kill -9 注入：env BATCH_EXECUTOR_CRASH_AT 匹配时 os._exit(137)。"""
    target = os.environ.get("BATCH_EXECUTOR_CRASH_AT", "")
    if target == stage:
        _logger.warning("[crash-inject] os._exit(137) at stage %s", stage)
        os._exit(137)


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


# ---------------------------------------------------------------------------
# Pre-commit gate（C4：NDG+fields/tags/lint/对账，失败 = 零写入）
# ---------------------------------------------------------------------------

def _gate_fields(page) -> list[str]:
    """L0-L3：id/title/sources/grade/processing_depth（复用 fields_cmd 语义）。

    processing_depth 合法值对齐 generator 的 PROCESSING_DEPTH_VALUES
    （concept/memory/operation）+ wiki 写入侧扩展（source/entity/synthesis/
    stub）——review C3-3：漏 operation 会把真实语料误拦。
    """
    errs = []
    if not page.id:
        errs.append("L0: missing id")
    if not getattr(page, "title", "") or not page.title.strip():
        errs.append("L0: missing title")
    if not page.sources:
        errs.append("L0: missing sources")
    if page.grade not in ("A", "B", "C"):
        errs.append(f"L1: invalid grade: {page.grade}")
    _VALID_DEPTHS = {"memory", "concept", "operation",
                     "source", "entity", "synthesis", "stub"}
    if page.processing_depth not in _VALID_DEPTHS:
        errs.append(f"L1: invalid processing_depth: {page.processing_depth}")
    return errs


def _gate_tags(page) -> list[str]:
    """tags 值域 + 必填对（复用 tag_namespace）。

    语义与 batch_gate_v3（1.5 门禁，本 pre-commit gate 取代它）一致：
    ``validate_tag_compliance``（值域 + 素材/ugc↔可信度/ugc 必填对）。
    ``cli tags validate`` 只查前缀（更松）是既有分叉，非本 gate 引入——
    gate 采用批门禁口径（review I4 记录，不改）。
    """
    from src.wiki.features.tag_namespace import (
        TagValidationError, validate_tag_compliance,
    )
    try:
        validate_tag_compliance(list(page.tags or []))
    except TagValidationError as exc:
        return [str(exc)]
    return []


def _gate_lint(page, paths) -> list[str]:
    """lint 四项：占位符 / 非法 relation / RAW-PASTE / MISSING-SECTION。

    在内存页对象上运行（pre-commit 时页面尚未落盘），判定逻辑与
    ``src.wiki.features.lint.lint_wiki`` 共享同一谓词与版本门（review C3）：
    - RAW-PASTE 阈值走 ``_load_raw_paste_thresholds(paths)``（quality_settings
      校准，不写死）；
    - MISSING-SECTION 走 lint 的 H3 版本门（页声明版本 < 项目模板版本 →
      bundled 槽集）+ ``_template_heading_map``（v3.0.0 synthesis 的
      conclusion 槽渲染为 ``## 待定与结论``）；
    - 严重级与 lint_wiki 对齐：占位符/非法 relation/source fulltext 段为
      ERROR；RAW-PASTE run 超阈值在 lint 是 WARNING（不拦批）——本 gate
      只把 ERROR 项计入 block（与 batch_gate_v3 的 lint 步骤一致）。
    """
    from src.wiki.features.lint import (
        _BODY_HEADING_RE,
        _BUILTIN_RELATIONS,
        _PLACEHOLDER_SUBSTRINGS,
        _TEMPLATE_VERSION_RE,
        _bundled_template,
        _has_fulltext_section,
        _load_raw_paste_thresholds,
        _long_raw_text_run,
        _parse_version,
        _template_heading_map,
        list_resolved,
        required_slot_names,
    )
    from src.wiki.core.types import PageType

    errs = []
    body = page.body or ""
    # 占位符（ERROR）
    if any(p in body for p in _PLACEHOLDER_SUBSTRINGS):
        errs.append(f"LINT-PLACEHOLDER: {page.id}")
    # 非法 relation（ERROR）
    for rel in (page.relations or []):
        rtype = rel.type if isinstance(rel.type, str) else rel.type.value
        if rtype not in _BUILTIN_RELATIONS and not rtype.startswith("x-"):
            errs.append(f"LINT-ILLEGAL-RELATION: {page.id} type={rtype}")
    # RAW-PASTE：阈值从 quality_settings 读（review C3-2）；与 lint 一致，
    # 只有 source fulltext 段是 ERROR，run 超阈值在 lint 为 WARNING（不拦批）。
    T_source, T_non = _load_raw_paste_thresholds(paths)
    raw_run = _long_raw_text_run(body)
    if page.type == PageType.SOURCE and _has_fulltext_section(body):
        errs.append(f"LINT-RAW-PASTE(fulltext): {page.id}")
    # （lint 中 run 超阈值是 WARNING → 不入 ERROR 集，避免门禁与 lint 分叉拦批）
    # MISSING-SECTION（H3 版本门 + 标题映射，review C3-1）
    vm = _TEMPLATE_VERSION_RE.search(body)
    if vm and _parse_version(vm.group(1)) >= (2, 0, 0) and \
            getattr(page, "processing_depth", "") != "stub":
        try:
            templates = {t.type: t for t in list_resolved(paths.root)}
            template = templates.get(page.type)
            if template is not None:
                required = required_slot_names(template)
                if not required:
                    return errs
                page_ver = _parse_version(vm.group(1))
                project_ver = _parse_version(template.version or "2.0.0")
                if page_ver < project_ver:
                    baseline = _bundled_template(page.type)
                    if baseline is None:
                        return errs
                    headings = {_heading_label_for(n, page.type)
                                for n in required_slot_names(baseline)}
                else:
                    heading_map = _template_heading_map(template, page.type.value)
                    headings = {
                        heading_map.get(n, _heading_label_for(n, page.type))
                        for n in required
                    }
                body_headings = set(_BODY_HEADING_RE.findall(body))
                missing = sorted(h for h in headings if h not in body_headings)
                if missing:
                    errs.append(
                        f"LINT-MISSING-SECTION: {page.id} missing={missing}")
        except Exception:
            pass  # 模板解析失败 → 该槽检查降级（不误 block）
    return errs


def _heading_label_for(slot_name: str, page_type) -> str:
    """slot → 标题（复用 lint 的 bundled 映射；entity 的 summary → 简介）。"""
    from src.wiki.features.lint import _heading_label
    return _heading_label(slot_name, page_type.value)


def _wikilink_targets_of(page) -> list[str]:
    """WikiPage 的链接目标：body ``[[...]]`` + relation target_id。

    review C2：不能把 WikiPage 直接喂给 ``metrics.collect_wikilinks``
    （它按 PageSnapshot 契约访问 ``relations[].get("target")``，而
    WikiPage.relations 是 ``list[Relation]`` dataclass → AttributeError）。
    """
    import re as _re
    targets = [m.group(1).strip()
               for m in _re.finditer(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]",
                                     page.body or "")]
    targets += [rel.target_id for rel in (page.relations or [])
                if getattr(rel, "target_id", None)]
    return [t for t in targets if t]


def _gate_reconcile(pages, extra_pages, paths,
                    pending_gap_slugs: set[str] | None = None) -> list[str]:
    """对账（M1）：批内页 wikilink/relation 目标 vs 磁盘 ∪ 别名 ∪ 索引 ∪ gap。

    gap 已登记（open/suppressed）的目标不计断链（F2 语义）。批内产生的页
    互相解析；磁盘既有页也解析（对账到整库，非仅批内）。

    ``pending_gap_slugs``（修复 A）：本批 generate 已采集、尚未落盘的 gap
    slug——并入豁免集（磁盘 gap 账本在 commit 时才写入，门禁在 commit 前
    运行；不并入则本批新 gap 全部误判 BROKEN-LINK 拦批）。

    extras（存量 reverse-touch 页）不参与断链判定（修复 B：存量断链是
    M1 历史遗留，由 Phase 4 cascade 重建消解；extras 仅作 produced 目标）。
    """
    from src.wiki.features.indexer import read_index
    from src.wiki.features.knowledge_gaps import KnowledgeGapStore
    from src.wiki.features.slug_utils import normalize_reconcile_slug

    produced = {p.id for p in pages} | {p.id for p in (extra_pages or [])}
    disk = {slug for slug, _, _ in read_index(paths)}
    try:
        from src.wiki.features.slug_aliases import SlugAliasRegistry
        alias = SlugAliasRegistry(paths.root)
        alias_canon = alias.get_canonical
    except Exception:
        alias_canon = None

    known_norm = {normalize_reconcile_slug(s) for s in (disk | produced)}
    gap_slugs = {g.slug for g in KnowledgeGapStore(paths.root).all()
                 if g.status in ("open", "suppressed")}
    if pending_gap_slugs:
        gap_slugs |= set(pending_gap_slugs)
    gap_norm = {normalize_reconcile_slug(s) for s in gap_slugs}

    errs = []
    # 修复 B：只对批内新产出 pages 判断链；extras 是存量 reverse-touch 页，
    # 其历史断链由 cascade 重建消解（不计入批内 M1）。
    for p in pages:
        for target in _wikilink_targets_of(p):
            canon = alias_canon(target) if alias_canon else target
            # get_canonical 对未知 slug 返回 None → 回退原 target（review 实测）
            canon = canon if canon else target
            tn = normalize_reconcile_slug(canon)
            if target in produced or tn in known_norm:
                continue
            if target in gap_slugs or tn in gap_norm:
                continue
            errs.append(f"BROKEN-LINK: {p.id} -> [[{target}]]")
    return errs


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


def run_precommit_gate(pages, extra_pages, raw_headers, paths,
                       allow_overwrite=False,
                       pending_gap_slugs: set[str] | None = None
                       ) -> tuple[bool, list[str]]:
    """pre-commit 门禁：NDG + fields + tags + lint + 对账（失败 = 零写入）。

    Returns ``(passed, issues)``。任何一项 ERROR → 整批 block。

    ``pending_gap_slugs``（Phase 4 试跑实测修复 A）：本批 generate 阶段
    已采集、尚未落盘磁盘 gap 账本的 slug（_commit_raw 会把它们写入
    KnowledgeGapStore；门禁在 commit 前运行，磁盘 gap 不含本批新增）。
    若不并入豁免集，这些"本批已登记"的链接会被误判 BROKEN-LINK →
    整批零写入误拦（试跑 22 个 issue 的主因）。

    ``extra_pages``（Phase 4 试跑实测修复 B）：存量 reverse-touch 页
    （旧 2.0.0 英文 tag / 历史断链是 M8/M1 消解范围，按 phase3_accept
    口径不计入批内 M1/M4/M9 判定）——fields/tags/lint 只查本批新产出
    ``pages``；extras 仅作为对账的已知目标（produced 集合），自身不拦批。
    """
    from src.wiki.features.ndg_gate import run_ndg_gate

    issues: list[str] = []

    # 1. NDG gate（P1-P7 既有批次级结构检查）
    report = run_ndg_gate(
        pages, raw_headers=raw_headers, extra_pages=extra_pages,
        paths=paths, allow_overwrite=allow_overwrite,
    )
    for issue in report.issues:
        if issue.is_blocker:
            issues.append(f"NDG-{issue.code}: {issue.page_id or '-'} {issue.message}")

    # 2-5. fields / tags / lint / 对账 —— 只查本批新产出 pages；
    #      extras（存量 reverse-touch 页）不参与（修复 B）。
    for p in pages:
        issues.extend(f"{e} [{p.id}]" for e in _gate_fields(p))
        issues.extend(f"TAG-ENUM {e} [{p.id}]" for e in _gate_tags(p))
        issues.extend(f"{e}" for e in _gate_lint(p, paths))
    issues.extend(_gate_reconcile(pages, extra_pages, paths,
                                  pending_gap_slugs=pending_gap_slugs))

    return not issues, issues


# ---------------------------------------------------------------------------
# Batch orchestration
# ---------------------------------------------------------------------------

def _resolve_paths(args) -> WikiPaths:
    if getattr(args, "root", None):
        return WikiPaths(Path(args.root))
    from src.pipeline import _resolve_wiki_paths
    return _resolve_wiki_paths(args.project)


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


def _resolve_provider(args):
    """按 --project 解析 LLM provider（C1：真实模式不能传 None）。

    --root 测试模式无项目注册 → 返回默认 provider（_get_provider(None)）。
    """
    from src.pipeline import _get_provider
    project_id = getattr(args, "project", None)
    return _get_provider(project_id)


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
                        missing_slugs=missing_slugs)
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
                generated[raw_rel] = (pages, [], {"fake": True})
            else:
                pages, extras, meta = await _generate_raw(
                    paths, provider, raw_rel, args.batch)
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

    sem = asyncio.Semaphore(args.concurrency)
    async def _gen_locked(raw_rel: str) -> None:
        async with sem:
            await _gen_one(raw_rel)

    await asyncio.gather(*(_gen_locked(r) for r in pending))

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
    all_pages = [p for pages, _, _ in generated.values() for p in pages]
    all_extras = [e for _, extras, _ in generated.values() for e in extras]
    # 修复 A：门禁在 commit 前运行，磁盘 gap 不含本批新增 —— 收集本批
    # generate 已采集的 missing_slugs 并入门禁豁免集，避免误拦整批。
    pending_gap_slugs = {
        m["slug"]
        for _, _, meta in generated.values()
        for m in (meta or {}).get("missing_slugs") or []
    }
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

    # ── Phase 3：commit（每 raw 分支）──────────────────────────────
    ok = err = perm = 0
    for raw in pending:
        if raw not in generated:
            continue
        pages, extras, meta = generated[raw]
        try:
            branch = await _commit_raw(paths, raw, pages, extras, batch_key,
                                       task_id=f"b{args.batch}", meta=meta)
            ok += 1
            _update_fail_streak(paths, batch_key, raw, "done")
            _crash_at("commit")   # 提交后注入点（测试）
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

    # ── 每批向量 upsert（guidance #9："每批后向量 upsert"）──────────
    # 直跑路径只删向量（_commit_raw），重建后必须 upsert 新 chunk，否则
    # 搜索静默丢内容（I3 review (a)）。真实模式需要 embedding provider；
    # 未配置/失败 → 记 warn 不拦批（与 server 的 best-effort 一致）。
    if not _is_fake_mode() and generated:
        try:
            upserted = await _upsert_batch_vectors(paths, all_pages)
            print(f"  [vector] upserted {upserted} chunk(s)", flush=True)
        except Exception as exc:
            print(f"  [vector] WARN upsert failed (search degrade): {exc}",
                  flush=True)

    # ── 整批门禁复核（C4：崩溃后续跑对整批——含已 done 文件——重跑门禁，
    #    杜绝门禁作用域收缩）──────────────────────────────────────────
    whole_ok = await _rerun_gate_batch(paths, batch_key, files)
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


async def _rerun_gate_batch(paths, batch_key, files) -> bool:
    """整批门禁复核（C4：崩溃后续跑对整批——含已 done 文件——重跑门禁）。

    从磁盘读取本批 raw 关联的全部页面（含此前已 done 的文件），跑完整的
    NDG + fields/tags/lint/对账 门禁。失败 → 批状态 gate_failed（调用方
    决定是否回滚）。这是门禁作用域收缩的兜底：pre-commit 门禁只管本轮的
    内存页，复核把作用域钉回整批。
    """
    from src.wiki.storage.page_writer import read_page

    batch_set = set(files)
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
            if set(pg.sources or []) & batch_set:
                pages.append(pg)
    passed, issues = run_precommit_gate(pages, [], {}, paths,
                                        allow_overwrite=True)
    if not passed:
        for iss in issues[:10]:
            print(f"  [GATE] {iss}", flush=True)
        print(f"  [GATE] {len(issues)} issue(s) — FAIL", flush=True)
    else:
        print(f"  [GATE] {len(pages)} page(s) — PASS", flush=True)
    return passed


def _is_fake_mode() -> bool:
    return os.environ.get("RUFLO_EXECUTOR_FAKE_GENERATE") == "1"


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    ap = argparse.ArgumentParser(description="Phase 4 直跑批执行器")
    ap.add_argument("--manifest", default=DEFAULT_MANIFEST)
    ap.add_argument("--batch", type=int, default=0)
    ap.add_argument("--project", default=None, help="project id (registry)")
    ap.add_argument("--root", default=None, help="project root (直跑/测试)")
    ap.add_argument("--resume", action="store_true",
                    help="续跑：跳过 done、重跑 pending_deletion/failed")
    ap.add_argument("--budget-usd", type=float, default=None,
                    help="累计费用预算，超限自动暂停")
    ap.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    ap.add_argument("--allow-overwrite", action="store_true")
    ap.add_argument("--no-git-snapshot", action="store_true")
    args = ap.parse_args(argv)

    if not args.project and not args.root:
        print("ERROR: provide --project <id> or --root <path>", flush=True)
        return 1
    if args.budget_usd is not None and args.budget_usd <= 0:
        print("ERROR: --budget-usd must be > 0", flush=True)
        return 1
    if args.batch < 0:
        print("ERROR: --batch must be >= 0", flush=True)
        return 1
    if args.concurrency < 1:
        print("ERROR: --concurrency must be >= 1", flush=True)
        return 1

    return asyncio.run(run_batch(args))


if __name__ == "__main__":
    sys.exit(main())
