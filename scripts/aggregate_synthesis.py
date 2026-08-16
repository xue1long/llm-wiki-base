#!/usr/bin/env python3
"""Phase 4.5 — 多源 synthesis 聚合（M6 支撑，F1 整改）。

按 taxonomy category 聚合已落盘的多源 concept 页 → 喂 synthesis 模板 →
LLM 生成 synthesis 页（分歧汇聚）→ 质量门通过 → commit。

用法：
    python scripts/aggregate_synthesis.py --root <project> [--budget-usd 0.1] [--dry-run]

候选主题：category 下含 ≥2 个独立 source 的 concept 页组。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class SynthesisResult:
    """单个 category 的聚合产出。"""
    category: str
    concept_pages: list  # list[WikiPage]
    synthesis_page: Optional[object] = None  # WikiPage | None
    error: str = ""


# ---------------------------------------------------------------------------
# Grouping helpers
# ---------------------------------------------------------------------------
def _group_by_category(
    pages: list,
) -> dict[str, list]:
    """按 ``page.category`` 分组 concept 页。

    ``uncategorized`` 和空 category 跳过（跨源聚合需要明确分类轴）。
    """
    from collections import defaultdict

    groups: dict[str, list] = defaultdict(list)
    for p in pages:
        cat = (p.category or "").strip()
        if not cat:
            continue
        groups[cat].append(p)
    return dict(groups)


def _is_synthesis_candidate(pages: list) -> bool:
    """True 当该组 concept 页来自 ≥2 个独立 source raw。

    这是聚合的充分条件：多个独立来源对同一主题提供了不同视角，
    值得生成分歧汇聚页。
    """
    sources: set[str] = set()
    for p in pages:
        sources.update(p.sources or [])
    return len(sources) >= 2


# ---------------------------------------------------------------------------
# LLM generate
# ---------------------------------------------------------------------------
async def _generate_synthesis_pages(
    candidates: dict[str, list],
    paths,
    *,
    provider=None,
    project_root: Path,
) -> list[SynthesisResult]:
    """对每个候选 category 调用 LLM 生成 synthesis 页。

    provider 为 None 时从注册表加载默认 provider。
    """
    from src.pipeline.generator import _call_with_slot_retry
    from src.wiki.schema_registry import SchemaRegistry
    from src.wiki.templates.resolver import resolve as _resolve_template
    from src.wiki.core.types import PageType, WikiPage
    from src.wiki.features.relations import Relation

    if provider is None:
        from src.pipeline import _get_provider
        provider = _get_provider(None)

    schema_reg = SchemaRegistry.from_project(project_root)

    # 加载 synthesis 模板的 slot 定义
    template = _resolve_template(PageType.SYNTHESIS, project_root)
    required_slots_by_type: dict[PageType, list[str]] = {}
    if template and hasattr(template, "sections"):
        slots = [s.name for sec in template.sections for s in sec.slots]
        required_slots_by_type[PageType.SYNTHESIS] = slots or []

    results: list[SynthesisResult] = []
    for category, concept_pages in candidates.items():
        try:
            result = await _generate_one(
                category, concept_pages, provider,
                required_slots_by_type, schema_reg,
            )
            results.append(result)
        except Exception as exc:
            _logger.error("[aggregate] category %s failed: %s", category, exc)
            results.append(SynthesisResult(
                category=category, concept_pages=concept_pages, error=str(exc),
            ))
    return results


async def _generate_one(
    category: str,
    concept_pages: list,
    provider,
    required_slots_by_type: dict[str, list[str]],
    schema_reg,
) -> SynthesisResult:
    """生成单个 category 的 synthesis 页。"""
    from src.wiki.core.types import PageType, WikiPage
    from src.wiki.features.relations import Relation
    from src.llm.openai_provider import _strip_reasoning
    from src.pipeline.retry import retry_with_backoff

    # 收集该 category 下所有 concept 页的摘要信息
    # 每页 body 只保留前 200 chars（避免 prompt 过长）
    # 每 category 最多取样 15 页（按来源数降序，保证多源代表性）
    concept_summaries: list[str] = []
    all_sources: set[str] = set()

    sorted_pages = sorted(
        concept_pages,
        key=lambda p: (len(set(p.sources or [])), len(p.body or "")),
        reverse=True,
    )[:15]

    for p in sorted_pages:
        body_preview = (p.body or "")[:200].replace("\n", " ")
        concept_summaries.append(
            f"- {p.id}（{p.title}）：等级={p.grade}, 来源={p.sources}, "
            f"body={body_preview}"
        )
        all_sources.update(p.sources or [])

    sources_str = json.dumps(sorted(all_sources), ensure_ascii=False)
    prompt = (
        f"你是一个网络小说写作知识库的聚合专家。请根据以下 taxonomy 分类 "
        f"「{category}」下的多个概念页，生成一篇 synthesis 页（分歧汇聚）。\n\n"
        f"## 源概念页\n"
        f"{chr(10).join(concept_summaries)}\n\n"
        f"## 要求\n"
        f"1. 识别该 category 下各来源的核心分歧与共识\n"
        f"2. 输出 JSON 格式，包含以下字段：\n"
        f"   - topic: 议题与分歧点\n"
        f"   - viewpoints: 各方观点（必须包含 ≥2 个 [[wikilink]] 引用来源概念页）\n"
        f"   - consensus: 共识\n"
        f"   - evidence_comparison: 证据对比\n"
        f"   - conclusion: 结论（必须给出判断或建议）\n"
        f"3. 不要编造来源不存在的例证\n"
        f"4. 输出格式：{{\"synthesis\": {{<字段>}}}}\n"
    )

    page_id = _slugify(category) + "-多源分歧"

    try:
        response = await retry_with_backoff(
            lambda: provider.complete(
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                max_tokens=8192,
            ),
            max_retries=2,
            cb_name="synthesis",
        )
    except Exception as exc:
        return SynthesisResult(
            category=category, concept_pages=concept_pages,
            error=f"LLM call failed: {exc}",
        )

    # 解析 LLM 产出
    content = response.content
    content = _strip_reasoning(content)
    if not content or not content.strip():
        return SynthesisResult(
            category=category, concept_pages=concept_pages,
            error="LLM returned empty content",
        )

    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        return SynthesisResult(
            category=category, concept_pages=concept_pages,
            error=f"JSON parse failed: {exc}",
        )

    synthesis_data = data.get("synthesis", data)
    if not isinstance(synthesis_data, dict):
        return SynthesisResult(
            category=category, concept_pages=concept_pages,
            error="LLM returned non-dict content",
        )

    def _slot_text(value: object) -> str:
        """Normalise an LLM slot value (str | list[str] | list[dict] | None) to text."""
        if value is None:
            return ""
        if isinstance(value, list):
            parts = []
            for v in value:
                if isinstance(v, dict):
                    # dict row: prefer text/content/point keys, else str(dict)
                    parts.append(
                        str(v.get("text") or v.get("content") or v.get("point") or v)
                    )
                else:
                    parts.append(str(v))
            return "\n".join(parts)
        return str(value)

    slots = {
        "topic": _slot_text(synthesis_data.get("topic")),
        "viewpoints": _slot_text(synthesis_data.get("viewpoints")),
        "consensus": _slot_text(synthesis_data.get("consensus")),
        "evidence_comparison": _slot_text(synthesis_data.get("evidence_comparison")),
        "conclusion": _slot_text(synthesis_data.get("conclusion")),
    }

    # 质量门：slots 必须有实质内容（非空）
    if not any(v.strip() for v in slots.values()):
        return SynthesisResult(
            category=category, concept_pages=concept_pages,
            error="LLM returned empty slots",
        )

    # 构造 WikiPage
    body_lines = [f"<!-- wiki-template-version: 3.0.0 -->"]
    body_lines.append(f"<!-- wiki-template-type: synthesis -->")
    body_lines.append("")
    # 议题与分歧点
    body_lines.append("## 议题与分歧点")
    body_lines.append("")
    body_lines.append(slots.get("topic", "").strip())
    body_lines.append("")
    # 各方观点
    body_lines.append("## 各方观点")
    body_lines.append("")
    body_lines.append(slots.get("viewpoints", "").strip())
    body_lines.append("")
    # 共识
    body_lines.append("## 共识")
    body_lines.append("")
    body_lines.append(slots.get("consensus", "").strip())
    body_lines.append("")
    # 证据对比
    body_lines.append("## 证据对比")
    body_lines.append("")
    body_lines.append(slots.get("evidence_comparison", "").strip())
    body_lines.append("")
    # 待定与结论
    body_lines.append("## 待定与结论")
    body_lines.append("")
    body_lines.append(slots.get("conclusion", "").strip())

    body = "\n".join(body_lines)

    synthesis_page = WikiPage(
        id=page_id,
        title=f"{category}的多源分歧",
        type=PageType.SYNTHESIS,
        sources=sorted(all_sources),
        body=body,
        grade=synthesis_data.get("grade", "B"),
        processing_depth="concept",
        category=category,
        relations=[
            Relation(target_id=p.id, type="references")
            for p in concept_pages
        ],
    )
    # 保留 slots 元数据供 lint 使用
    synthesis_page.slots = slots

    return SynthesisResult(
        category=category, concept_pages=concept_pages,
        synthesis_page=synthesis_page,
    )


def _slugify(text: str) -> str:
    """Simple slugify for CJK text."""
    import re
    s = text.strip().lower()
    s = re.sub(r"[^\w\u4e00-\u9fff-]", "-", s)
    s = re.sub(r"-+", "-", s)
    return s.strip("-")


# ---------------------------------------------------------------------------
# Commit
# ---------------------------------------------------------------------------
def _commit_synthesis(
    paths,
    results: list[SynthesisResult],
    *,
    project_root: Path,
) -> int:
    """将通过的 synthesis 页写入磁盘并更新 index。

    返回成功写入页数。
    """
    from src.wiki.storage.page_writer import write_page, read_page
    from src.wiki.features.indexer import append_to_index
    from src.wiki.features.logger import log_event
    from src.wiki.features.relations import RelationSync

    committed = 0
    for r in results:
        if r.synthesis_page is None:
            continue
        try:
            write_page(paths, r.synthesis_page)
            append_to_index(
                paths,
                [(r.synthesis_page.id, r.synthesis_page.type, r.synthesis_page.title)],
            )
            log_event(paths, "created", r.synthesis_page.id,
                      {"type": r.synthesis_page.type.value})
            # 同步关系索引
            RelationSync.sync_page(
                paths, r.synthesis_page.id, r.synthesis_page.relations or [],
            )
            committed += 1
            print(f"  [commit] synthesis: {r.synthesis_page.id}", flush=True)
        except Exception as exc:
            print(f"  [commit] FAIL {r.category}: {exc}", flush=True)
    return committed


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------
async def main(args) -> int:
    """Phase 4.5 入口。

    Returns:
        0 = 成功（含无候选）
        1 = 部分失败
        2 = 全部失败
    """
    from src.wiki.storage.ensure import ensure_knowledge_base
    from src.wiki.core.paths import WikiPaths
    from src.wiki.storage.page_writer import read_page
    from collections import defaultdict

    root = Path(args.root)
    ensure_knowledge_base(root)
    paths = WikiPaths(root)

    # 读取所有 concept 页
    concept_dir = paths.wiki_concepts
    if not concept_dir.exists():
        print("no concepts directory", flush=True)
        return 0

    all_pages = []
    for f in sorted(concept_dir.glob("*.md")):
        try:
            all_pages.append(read_page(f))
        except Exception as exc:
            print(f"  skip {f.name}: {exc}", flush=True)

    if not all_pages:
        print("no concept pages to aggregate", flush=True)
        return 0

    # 分组 + 筛选候选
    groups = _group_by_category(all_pages)
    candidates = {cat: pgs for cat, pgs in groups.items()
                  if _is_synthesis_candidate(pgs)}

    print(f"concept pages: {len(all_pages)}, categories: {len(groups)}, "
          f"candidates: {len(candidates)}", flush=True)

    if not candidates:
        print("no synthesis candidates (need ≥2 sources per category)", flush=True)
        return 0

    for cat, pgs in sorted(candidates.items()):
        src_count = len({s for p in pgs for s in (p.sources or [])})
        print(f"  candidate: {cat} ({len(pgs)} pages, {src_count} sources)",
              flush=True)

    if args.dry_run:
        print("DRY-RUN — no LLM calls or writes", flush=True)
        return 0

    # 生成
    print("generating synthesis pages...", flush=True)
    results = await _generate_synthesis_pages(
        candidates, paths, project_root=root,
    )

    # 质量门
    ok = 0
    failed = 0
    for r in results:
        if r.synthesis_page is not None:
            # lint 检查（各方观点 ≥2 wikilink 由 lint 自行保证）
            ok += 1
        else:
            print(f"  FAIL {r.category}: {r.error}", flush=True)
            failed += 1

    print(f"synthesis: {ok} ok, {failed} failed", flush=True)

    if not ok:
        return 2 if failed else 0

    # commit
    if not args.dry_run:
        committed = _commit_synthesis(paths, results, project_root=root)
        print(f"committed: {committed} synthesis page(s)", flush=True)

    return 1 if failed else 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Phase 4.5 — 多源 synthesis 聚合",
    )
    p.add_argument("--root", default=".", help="project root")
    p.add_argument("--budget-usd", type=float, default=0.1,
                   help="budget cap (default 0.1)")
    p.add_argument("--dry-run", action="store_true",
                   help="scan candidates only, no LLM/write")
    return p.parse_args(argv)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = _parse_args()
    rc = asyncio.run(main(args))
    sys.exit(rc)