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
  2  门禁失败（零写入）
  3  预算超限暂停 或 POSTCHECK 失败
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
    save_batch_state,
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
    """L0-L3：id/title/sources/grade/processing_depth（复用 fields_cmd 语义）。"""
    errs = []
    if not page.id:
        errs.append("L0: missing id")
    if not getattr(page, "title", "") or not page.title.strip():
        errs.append("L0: missing title")
    if not page.sources:
        errs.append("L0: missing sources")
    if page.grade not in ("A", "B", "C"):
        errs.append(f"L1: invalid grade: {page.grade}")
    _VALID_DEPTHS = {"memory", "concept", "source", "entity", "synthesis", "stub"}
    if page.processing_depth not in _VALID_DEPTHS:
        errs.append(f"L1: invalid processing_depth: {page.processing_depth}")
    return errs


def _gate_tags(page) -> list[str]:
    """tags 值域 + 必填对（复用 tag_namespace）。"""
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
    ``src.wiki.features.lint.lint_wiki`` 共享同一谓词，杜绝口径分叉。
    """
    from src.wiki.features.lint import (
        _BODY_HEADING_RE,
        _BUILTIN_RELATIONS,
        _PLACEHOLDER_SUBSTRINGS,
        _TEMPLATE_VERSION_RE,
        _has_fulltext_section,
        _heading_label,
        _long_raw_text_run,
        _parse_version,
        list_resolved,
        required_slot_names,
    )

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
    # RAW-PASTE（source 页：fulltext 段 → ERROR；run 超阈值 → ERROR）
    raw_run = _long_raw_text_run(body)
    if page.type.value == "source" and _has_fulltext_section(body):
        errs.append(f"LINT-RAW-PASTE(fulltext): {page.id}")
    elif page.type.value == "source" and raw_run > 800:
        errs.append(f"LINT-RAW-PASTE(source): {page.id} run={raw_run}")
    elif page.type.value != "source" and raw_run > 300:
        errs.append(f"LINT-RAW-PASTE(non-source): {page.id} run={raw_run}")
    # MISSING-SECTION（版本门 >= 2.0.0；stub 豁免）
    vm = _TEMPLATE_VERSION_RE.search(body)
    if vm and _parse_version(vm.group(1)) >= (2, 0, 0) and \
            getattr(page, "processing_depth", "") != "stub":
        try:
            templates = {t.type: t for t in list_resolved(paths.root)}
            template = templates.get(page.type)
            if template is not None:
                required = required_slot_names(template)
                if required:
                    headings = {
                        _heading_label(n, page.type.value) for n in required
                    }
                    body_headings = set(_BODY_HEADING_RE.findall(body))
                    missing = sorted(h for h in headings if h not in body_headings)
                    if missing:
                        errs.append(
                            f"LINT-MISSING-SECTION: {page.id} missing={missing}")
        except Exception:
            pass  # 模板解析失败 → 该槽检查降级（不误 block）
    return errs


def _gate_reconcile(pages, extra_pages, paths) -> list[str]:
    """对账（M1）：批内页 wikilink/relation 目标 vs 磁盘 ∪ 别名 ∪ 索引 ∪ gap。

    gap 已登记（open/suppressed）的目标不计断链（F2 语义）。批内产生的页
    互相解析；磁盘既有页也解析（对账到整库，非仅批内）。
    """
    from src.wiki.features.indexer import read_index
    from src.wiki.features.knowledge_gaps import KnowledgeGapStore
    from src.wiki.features.slug_utils import normalize_reconcile_slug
    from src.wiki.features.metrics import collect_wikilinks

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
    gap_norm = {normalize_reconcile_slug(s) for s in gap_slugs}

    errs = []
    for p in pages + (extra_pages or []):
        for target in collect_wikilinks(p):
            canon = alias_canon(target) if alias_canon else target
            tn = normalize_reconcile_slug(canon)
            if target in produced or tn in known_norm:
                continue
            if target in gap_slugs or tn in gap_norm:
                continue
            errs.append(f"BROKEN-LINK: {p.id} -> [[{target}]]")
    return errs


def run_precommit_gate(pages, extra_pages, raw_headers, paths,
                       allow_overwrite=False) -> tuple[bool, list[str]]:
    """pre-commit 门禁：NDG + fields + tags + lint + 对账（失败 = 零写入）。

    Returns ``(passed, issues)``。任何一项 ERROR → 整批 block。
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

    # 2-5. fields / tags / lint / 对账
    for p in pages + (extra_pages or []):
        issues.extend(f"{e} [{p.id}]" for e in _gate_fields(p))
        issues.extend(f"TAG-ENUM {e} [{p.id}]" for e in _gate_tags(p))
        issues.extend(f"{e}" for e in _gate_lint(p, paths))
    issues.extend(_gate_reconcile(pages, extra_pages, paths))

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


async def _commit_raw(paths, raw_rel, pages, extras, batch_key, task_id) -> str:
    """Phase 3：按分支提交单个 raw。返回分支名（reingest / first_ingest）。

    C2：有 source 页 → reingest（记 pending_deletion → cascade_delete +
    删向量 → commit 新页）；无 → 首摄 commit。cascade 抛 FileNotFoundError
    （源页被删）→ 降级首摄而非 failed。
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
            init_vector_store_for_paths(paths)
            delete_by_source(paths, raw_rel)
            cascade_result.get("deleted_pages", [])
        _crash_at("cascade")
    await commit_ingest(paths, Path(raw_rel), pages, extras, task_id=task_id)
    set_raw_status(paths, batch_key, raw_rel, "done", branch=branch)
    return branch


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
        state = load_batch_state(paths)
        entry = state.setdefault(batch_key, {})
        entry["git_snapshot"] = snapshot
        entry["status"] = entry.get("status", "in_progress")
        entry["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        save_batch_state(paths, state)

    # 预算顶层检查：上次已超限 → 暂停
    state = load_batch_state(paths)
    cumulative = float(state.get("budget", {}).get("cumulative_usd", 0.0))
    if args.budget_usd is not None and cumulative > args.budget_usd:
        print(f"BUDGET PAUSED: cumulative ${cumulative:.2f} > "
              f"${args.budget_usd:.2f} — not starting batch", flush=True)
        entry = state.setdefault(batch_key, {})
        entry["status"] = "paused_budget"
        save_batch_state(paths, state)
        return 3

    # ── 状态机：决定每 raw 动作 ─────────────────────────────────────
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
        if st == "pending_deletion":
            print(f"RESUME pending_deletion: {raw} — re-running rebuild",
                  flush=True)
        pending.append(raw)

    if not pending:
        print("nothing to do — all files done/blocked", flush=True)
        return 0

    # 门禁先置 pending_gate（C4：批级状态，崩溃后续跑可识别）
    state = load_batch_state(paths)
    state.setdefault(batch_key, {})["status"] = "pending_gate"
    save_batch_state(paths, state)

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
                    paths, None, raw_rel, args.batch)
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
        state = load_batch_state(paths)
        entry = state.setdefault(batch_key, {})
        entry["status"] = "committed"
        entry["ok"] = len(skipped_immutable)
        entry["skipped_immutable"] = skipped_immutable
        entry["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        save_batch_state(paths, state)
        print(f"BATCH DONE (all {len(skipped_immutable)} immutable skipped)",
              flush=True)
        return 0

    if not generated:
        print(f"BATCH ABORTED: zero pages generated "
              f"(failed={len(failed_raws)} perm={len(perm_failed_raws)})",
              flush=True)
        state = load_batch_state(paths)
        entry = state.setdefault(batch_key, {})
        entry["status"] = "failed"
        entry["err"] = len(failed_raws)
        entry["permanent_failed"] = len(perm_failed_raws)
        save_batch_state(paths, state)
        return 1

    # ── Phase 2：pre-commit 门禁（内存页，失败 = 零写入）────────────
    all_pages = [p for pages, _, _ in generated.values() for p in pages]
    all_extras = [e for _, extras, _ in generated.values() for e in extras]
    gate_ok, gate_issues = run_precommit_gate(
        all_pages, all_extras, raw_headers, paths,
        allow_overwrite=args.allow_overwrite)
    if not gate_ok:
        print(f"BATCH BLOCKED: pre-commit gate failed — zero wiki writes "
              f"({len(gate_issues)} issue(s))", flush=True)
        for iss in gate_issues[:10]:
            print(f"  [GATE] {iss}", flush=True)
        state = load_batch_state(paths)
        entry = state.setdefault(batch_key, {})
        entry["status"] = "gate_failed"
        entry["gate_issues"] = gate_issues[:50]
        save_batch_state(paths, state)
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
                                       task_id=f"b{args.batch}")
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

    # ── 整批门禁复核（C4：崩溃后续跑对整批——含已 done 文件——重跑门禁，
    #    杜绝门禁作用域收缩）──────────────────────────────────────────
    whole_ok = await _rerun_gate_batch(paths, batch_key, files)
    _crash_at("gate")   # 门禁后注入点（测试）

    # ── 预算累计 + 批状态 ───────────────────────────────────────────
    state = load_batch_state(paths)
    cost = float(os.environ.get("RUFLO_FAKE_COST", "0.2")) if os.environ.get(
        "RUFLO_EXECUTOR_FAKE_GENERATE") == "1" else 0.0
    budget_state = state.setdefault("budget", {})
    budget_state["cumulative_usd"] = cumulative + cost
    budget_state["last_batch_usd"] = cost
    entry = state.setdefault(batch_key, {})
    if not whole_ok:
        entry["status"] = "gate_failed"
        entry["ok"] = ok
        entry["err"] = err
        save_batch_state(paths, state)
        print("BATCH GATE RE-CHECK FAILED (whole-batch scope) — review", flush=True)
        return 2
    if args.budget_usd is not None and budget_state["cumulative_usd"] > args.budget_usd:
        entry["status"] = "paused_budget"
        entry["ok"] = ok
        entry["err"] = err
        entry["permanent_failed"] = perm
        save_batch_state(paths, state)
        print(f"BUDGET PAUSED: cumulative ${budget_state['cumulative_usd']:.2f} "
              f"> ${args.budget_usd:.2f}", flush=True)
        return 3
    entry["status"] = "committed"
    entry["ok"] = ok
    entry["err"] = err
    entry["permanent_failed"] = perm
    entry["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    save_batch_state(paths, state)
    print(f"BATCH DONE ok={ok} err={err} permanent_failed={perm}", flush=True)
    return 0


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


def _install_fake_run_ingest() -> None:
    """RUFLO_EXECUTOR_FAKE_GENERATE=1：让 run_ingest（reingest 续跑）也走 fake。

    续跑时 pending_deletion 文件走 ``reingest_source_direct`` 内部的
    ``run_ingest``；fake 模式下把它换成 fake 生成 + 真实 commit，保证离线。
    """
    import src.pipeline.ingest as _pi_mod

    async def _fake_run_ingest(paths, source_path, source_text, provider,
                               folder_context="", task_id="test"):
        from src.pipeline.ingest import commit_ingest
        raw_rel = Path(str(source_path)).as_posix()
        pages = _fake_generate(raw_rel)
        await commit_ingest(paths, source_path, pages, task_id=task_id)
        return pages

    _pi_mod.run_ingest = _fake_run_ingest


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

    if _is_fake_mode():
        _install_fake_run_ingest()

    return asyncio.run(run_batch(args))


if __name__ == "__main__":
    sys.exit(main())
