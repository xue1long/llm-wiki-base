"""batch_gate.py — Pre-commit gate shared true source (extracted from batch_executor).

Extracted from ``scripts/batch_executor.py`` (P1-A 3a) so that the five gate
checks (NDG / fields / tags / lint / reconcile) live in one place and are
reusable across batch scripts, CLI subcommands, and integration tests.

Exports:
    - ``run_precommit_gate`` — the main entry point (returns (passed, issues))
    - ``_gate_fields``, ``_gate_tags``, ``_gate_lint``, ``_gate_reconcile``
      — individual checks (also used by diagnose_batch_gate.py)
"""
from __future__ import annotations

import re as _re
from pathlib import Path

from src.wiki.core.paths import WikiPaths
from src.wiki.core.types import PageType


# ---------------------------------------------------------------------------
# L0-L3 field checks
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


# ---------------------------------------------------------------------------
# Tags value-range check
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Lint checks (placeholder / illegal-relation / raw-paste / missing-section)
# ---------------------------------------------------------------------------

def _gate_lint(page, paths: WikiPaths) -> list[str]:
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


# ---------------------------------------------------------------------------
# Reconcile (M1 broken-link check)
# ---------------------------------------------------------------------------

def _wikilink_targets_of(page) -> list[str]:
    """WikiPage 的链接目标：body ``[[...]]`` + relation target_id。

    review C2：不能把 WikiPage 直接喂给 ``metrics.collect_wikilinks``
    （它按 PageSnapshot 契约访问 ``relations[].get("target")``，而
    WikiPage.relations 是 ``list[Relation]`` dataclass → AttributeError）。
    """
    targets = [m.group(1).strip()
               for m in _re.finditer(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]",
                                     page.body or "")]
    targets += [rel.target_id for rel in (page.relations or [])
                if getattr(rel, "target_id", None)]
    return [t for t in targets if t]


def _gate_reconcile(pages, extra_pages, paths: WikiPaths,
                    pending_gap_slugs: set[str] | None = None,
                    resolution_context=None) -> list[str]:
    """对账（M1）：批内页 wikilink/relation 目标 vs 磁盘 ∪ 别名 ∪ 索引 ∪ gap。

    gap 已登记（open/suppressed）的目标不计断链（F2 语义）。批内产生的页
    互相解析；磁盘既有页也解析（对账到整库，非仅批内）。

    ``pending_gap_slugs``（修复 A）：本批 generate 已采集、尚未落盘的 gap
    slug——并入豁免集（磁盘 gap 账本在 commit 时才写入，门禁在 commit 前
    运行；不并入则本批新 gap 全部误判 BROKEN-LINK 拦批）。

    ``resolution_context``（Task 5）：未解析目标经统一 resolver 判别多候选
    → ``TARGET-AMBIGUOUS``（可诊断），否则 ``BROKEN-LINK``。确定性失败不
    受 pending gap 豁免。

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
            # Task 5：统一 resolver 判别放在 gap 豁免之前 —— 确定性失败
            # （多候选）不被 pending_gap_slugs 业务缺口豁免。
            if resolution_context is not None:
                from src.wiki.features.target_resolver import resolve_wiki_target
                res = resolve_wiki_target(target, context=resolution_context)
                if res.kind == "ambiguous":
                    errs.append(
                        f"TARGET-AMBIGUOUS: {p.id} -> [[{target}]] "
                        f"candidates={res.candidates}"
                    )
                    continue
            if target in gap_slugs or tn in gap_norm:
                continue
            errs.append(f"BROKEN-LINK: {p.id} -> [[{target}]]")
    return errs


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_precommit_gate(pages, extra_pages, raw_headers, paths: WikiPaths,
                       allow_overwrite=False,
                       pending_gap_slugs: set[str] | None = None,
                       resolution_context=None
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

    ``resolution_context``（Task 5）：整批 source 候选的
    :class:`~src.wiki.features.target_resolver.ResolutionContext`。未解析
    目标经统一 resolver 二次判别：多候选 → ``TARGET-AMBIGUOUS``（可诊断
    阻断），否则保持 ``BROKEN-LINK``。确定性 resolver 失败绝不被
    ``pending_gap_slugs`` 豁免。
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
                                  pending_gap_slugs=pending_gap_slugs,
                                  resolution_context=resolution_context))

    return not issues, issues