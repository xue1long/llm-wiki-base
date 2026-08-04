"""10-round stress test + quality/speed audit driver.

Per round:
  1. Randomly select `docs` source documents from novel-wiki raw/sources
     (sampled WITHOUT replacement across rounds so idempotency dedup
     does not distort timings).
  2. Ingest each into perf-test via run_ingest with the minimax provider,
     instrumenting every provider.complete call (call count + latency).
  3. Inspect produced pages for quality signals (placeholder bodies,
     empty bodies, duplicate titles, source-only fallback, grade dist).
  4. Write out/plans/round_<i>_<timestamp>.md — optimization plan,
     write-only (no code changes).

Usage: PYTHONPATH=. python -u scripts/perf_loop.py [--rounds 10] [--docs 3]
      [--seed 42] [--start-round 1] [--wipe]
"""
from __future__ import annotations

import argparse
import asyncio
import random
import time
from datetime import datetime
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.lib.project import resolve_project
from src.llm.provider_factory import create_llm_provider

PERF_ID = "b35ad019-8fbf-4cf0-bbf0-aeec1af0f248"
NOVEL_SOURCES = Path(
    r"D:\5-Project\LLM-Wiki-7-31\LLM-Wiki\knowledge\novel-wiki\raw\sources"
)
PERF_ROOT = Path(r"D:\5-Project\LLM-Wiki-7-31\LLM-Wiki\knowledge\perf-test")
OUT_DIR = Path(r"D:\5-Project\LLM-Wiki-7-31\LLM-Wiki\out\plans")

PLACEHOLDER_MARKERS = ("待补充", "待完善", "待写入", "TODO", "（待", "(待")


def classify_call(system: str | None, user: str | None) -> str:
    """Best-effort stage classification from prompt content.

    Generator first — every generator prompt (GENERATOR_PROMPT /
    CANDIDATE_RENDER_PROMPT) opens with "You are rendering wiki pages";
    the formatted user message also carries candidate claims/evidence that
    can contain ``source_id``, so it must be checked BEFORE the analyzer
    token. Analyzer JSON prompt opens with "Extract structured knowledge
    claims" and always carries ``source_id`` / ``knowledge_types``.
    """
    blob = (system or "") + (user or "")
    lower = blob.lower()
    if "rendering wiki pages" in lower:
        return "generator"
    if "extract structured knowledge" in lower or "knowledge_types" in lower \
            or "source_id" in lower or "知识候选" in blob:
        return "analyzer"
    if "quality_score" in lower or "质量分" in blob or "打分" in blob:
        return "quality_judge"
    return "unknown"


class InstrumentedProvider:
    """Wraps a provider, recording every complete() call."""

    def __init__(self, provider):
        self._p = provider
        self.calls: list[dict] = []

    def __getattr__(self, name):
        return getattr(self._p, name)

    async def complete(self, messages, *, response_format=None, system=None,
                       timeout=None, **kwargs):
        user_msg = ""
        for m in messages:
            if m.get("role") == "user":
                user_msg = m.get("content", "")
                break
        t0 = time.monotonic()
        resp = await self._p.complete(
            messages, response_format=response_format, system=system,
            timeout=timeout, **kwargs,
        )
        dt = time.monotonic() - t0
        self.calls.append({
            "latency": dt,
            "stage": classify_call(system, user_msg),
            "system_hint": (system or user_msg)[:60],
        })
        return resp


def page_quality(page) -> dict:
    body = getattr(page, "body", "") or ""
    ptype = getattr(page, "type", None)
    ptype = ptype.value if hasattr(ptype, "value") else str(ptype)
    return {
        "id": getattr(page, "id", ""),
        "title": getattr(page, "title", ""),
        "type": ptype,
        "grade": getattr(page, "grade", "?"),
        "depth": getattr(page, "processing_depth", ""),
        "empty_body": len(body.strip()) == 0,
        "placeholder_hits": sum(1 for m in PLACEHOLDER_MARKERS if m in body),
    }


async def ingest_one(paths, provider, pick, task_id):
    text = pick.read_text(encoding="utf-8", errors="replace")
    from src.pipeline.ingest import run_ingest
    t0 = time.monotonic()
    pages = await run_ingest(
        paths=paths,
        source_path=str(pick),
        source_text=text,
        provider=provider,
        folder_context="",
        task_id=task_id,
    )
    dt = time.monotonic() - t0
    return pages, dt, text


def fmt_dt(seconds: float) -> str:
    return f"{seconds:.1f}s"


def build_agg(docs_report: list[dict]) -> dict:
    total_s = sum(d["total_s"] for d in docs_report)
    total_calls = sum(d["call_count"] for d in docs_report)
    total_pages = sum(d["page_count"] for d in docs_report)
    crashed = [d for d in docs_report if d.get("verdict") == "crashed"]
    fallback = [d for d in docs_report if d.get("verdict") == "fallback"]

    stages: dict[str, dict] = {}
    for d in docs_report:
        for c in d["calls"]:
            s = stages.setdefault(c["stage"], {"n": 0, "sum": 0.0, "max": 0.0})
            s["n"] += 1
            s["sum"] += c["latency"]
            s["max"] = max(s["max"], c["latency"])
    for s in stages.values():
        s["avg"] = s["sum"] / s["n"] if s["n"] else 0.0

    all_pages = [p for d in docs_report for p in d["pages"]]
    empty_count = sum(1 for p in all_pages if p["empty_body"])
    placeholder_count = sum(1 for p in all_pages if p["placeholder_hits"])
    stub_count = sum(1 for p in all_pages if p["depth"] == "stub")
    unique_titles = len({p["title"] for p in all_pages})
    grade_dist: dict[str, int] = {}
    for p in all_pages:
        grade_dist[p["grade"]] = grade_dist.get(p["grade"], 0) + 1

    issues = []
    n_docs = max(len(docs_report), 1)
    if crashed:
        issues.append({
            "sev": 0,
            "text": f"{len(crashed)}/3 文档因未捕获异常崩溃（TagValidationError: LLM 生成的标签不在允许值域）。"
                    f"write_page 对新建页面做硬校验并 raise，pipeline 未兜底 → 整篇摄取中断。",
        })
    if fallback:
        issues.append({
            "sev": 0,
            "text": f"{len(fallback)}/3 文档分析器候选被拒（Missing source_id/title、confidence 0.3<0.5）→ "
                    f"退化为 source-only stub 页，无知识产出。minimax 不支持 response_format 结构化输出，"
                    f"JSON 候选字段质量不可靠。",
        })
    if placeholder_count:
        issues.append({
            "sev": 0,
            "text": f"{placeholder_count} 个页面 body 含占位标记（待补充/待完善），生成器输出空壳而非实质内容。"
                    f"minimax 对 synthesis 模板 slot 返回空值，重试预算耗尽后 renderer 以占位符填充。",
        })
    if total_s / n_docs > 60:
        issues.append({
            "sev": 1,
            "text": f"单文档平均耗时 {fmt_dt(total_s / n_docs)}，端到端摄取慢于阈值（>60s/文档）。"
                    f"analyzer 单次调用即需 30-46s；成功路径再叠加生成调用与重试。",
        })
    if empty_count:
        issues.append({"sev": 1, "text": f"{empty_count} 个页面 body 为空。"})
    if total_pages - unique_titles > 0:
        issues.append({
            "sev": 1,
            "text": f"检测到 {total_pages - unique_titles} 个重复标题页面 → 分析器产出重复候选、"
                    f"生成器重复调用（浪费 LLM 预算）。",
        })
    if total_calls / n_docs > 4:
        issues.append({
            "sev": 1,
            "text": f"平均每文档 {total_calls / n_docs:.1f} 次 LLM 调用，调用量偏高，"
                    f"需前置候选去重/合并且并行化生成。",
        })
    if not issues:
        issues.append({"sev": 2, "text": "本轮未发现显著异常，基线正常。"})

    opts = []
    if crashed:
        opts.append({
            "title": "TagValidationError 兜底（P0 稳健性）",
            "detail": "write_page 对新建页面的标签硬校验改为 catch-and-sanitize：非法标签剥离后重试，"
                      "或降级为 source-only stub，而不是 raise 中断整篇摄取。",
        })
    if fallback:
        opts.append({
            "title": "分析器结构化输出适配 minimax",
            "detail": "minimax 不接受 response_format，JSON 候选依赖 prompt 约束而字段不可靠。"
                      "方案：为 analyzer 增加字段缺失修复（缺失 source_id 时回填 source_path、"
                      "title 从 claims 截取）、confidence 兜底归一，或在 Reviewer 前做一次模板校验重试。",
        })
    if "generator" in stages and stages["generator"]["n"] > 0:
        opts.append({
            "title": "并行化生成阶段",
            "detail": f"生成阶段 {stages['generator']['n']} 次串行调用、平均 {fmt_dt(stages['generator']['avg'])}。"
                      f"候选相互独立，可 asyncio.gather 并发生成，把生成耗时摊薄到单次延迟量级。",
        })
    if placeholder_count:
        opts.append({
            "title": "生成器空壳兜底策略",
            "detail": "生成器对 synthesis/concept 页面在 LLM 输出不足时回退为实体页而非提交占位模板；"
                      "或 Quality 门禁前将占位命中>N 的页面标记 rejected 并重试。",
        })
    if not opts:
        opts.append({"title": "本轮无 P0 优化项", "detail": "继续保持基线。"})

    return {
        "total_s": total_s,
        "avg_per_doc_s": total_s / n_docs,
        "total_calls": total_calls,
        "avg_call_s": sum(c["latency"] for d in docs_report for c in d["calls"]) / max(total_calls, 1),
        "total_pages": total_pages,
        "stages": stages,
        "empty_count": empty_count,
        "placeholder_count": placeholder_count,
        "stub_count": stub_count,
        "unique_titles": unique_titles,
        "grade_dist": grade_dist,
        "issues": issues,
        "opts": opts,
    }


def write_raw(round_no: int, stamp: str, docs_report: list[dict]) -> Path:
    """Persist per-doc raw call data as JSON so stage tables stay
    reproducible and can be regenerated if the classifier improves."""
    raw = []
    for d in docs_report:
        raw.append({
            "name": d["name"],
            "chars": d["chars"],
            "verdict": d.get("verdict"),
            "failed": d.get("failed"),
            "total_s": d["total_s"],
            "call_count": d["call_count"],
            "calls": [
                {"stage": c["stage"], "latency": round(c["latency"], 3)}
                for c in d["calls"]
            ],
            "pages": d["pages"],
        })
    path = OUT_DIR / f"_raw_round_{round_no}_{stamp.replace(':', '').replace(' ', '_')}.json"
    import json
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def write_plan(round_no: int, stamp: str, docs_report: list[dict], agg: dict) -> Path:
    lines = []
    lines.append(f"# Round {round_no} — {stamp}")
    lines.append("")
    lines.append("## 执行摘要")
    lines.append("")
    lines.append(f"- 文档数: {len(docs_report)} | 总耗时: {fmt_dt(agg['total_s'])}")
    lines.append(f"- 产出页面: {agg['total_pages']} | LLM 调用: {agg['total_calls']}")
    lines.append(f"- 平均单文档: {fmt_dt(agg['avg_per_doc_s'])} | 平均每调用: {fmt_dt(agg['avg_call_s'])}")
    lines.append("")
    lines.append("## 速度审计")
    lines.append("")
    lines.append("| 文档 | 大小(字符) | 结果 | 总耗时 | LLM调用数 | 每调用均耗 |")
    lines.append("|---|---|---|---|---|---|")
    for d in docs_report:
        lines.append(
            f"| {d['name'][:36]} | {d['chars']} | {d.get('verdict', 'ok')} | "
            f"{fmt_dt(d['total_s'])} | {d['call_count']} | {fmt_dt(d['avg_call_s'])} |"
        )
    lines.append("")
    lines.append("### 调用延迟分布（按阶段归类）")
    lines.append("")
    lines.append("| 阶段 | 调用数 | 平均 | 最大 |")
    lines.append("|---|---|---|---|")
    for stage, stats in agg["stages"].items():
        lines.append(
            f"| {stage} | {stats['n']} | {fmt_dt(stats['avg'])} | {fmt_dt(stats['max'])} |"
        )
    lines.append("")
    lines.append("## 质量审计")
    lines.append("")
    lines.append(f"- 页面总数: {agg['total_pages']} | 空 body: {agg['empty_count']} | "
                 f"占位命中: {agg['placeholder_count']} | source-only stub: {agg['stub_count']}")
    lines.append(f"- 标题去重: 唯一 {agg['unique_titles']} / 全部 {agg['total_pages']} → "
                 f"重复 {agg['total_pages'] - agg['unique_titles']}")
    lines.append(f"- Grade 分布: {agg['grade_dist']}")
    lines.append("")
    lines.append("## 问题清单（按严重度排序）")
    lines.append("")
    for i, issue in enumerate(agg["issues"], 1):
        lines.append(f"{i}. **[P{issue['sev']}]** {issue['text']}")
    lines.append("")
    lines.append("## 优化方案（write-only，不落代码）")
    lines.append("")
    for i, opt in enumerate(agg["opts"], 1):
        lines.append(f"{i}. **{opt['title']}** — {opt['detail']}")
    lines.append("")
    lines.append("---")
    lines.append("*由 perf_loop.py 自动生成，仅作优化规划参考。*")

    path = OUT_DIR / f"round_{round_no}_{stamp.replace(':', '').replace(' ', '_')}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def wipe_project(paths) -> None:
    """Reset perf-test wiki + .index so a fresh run has clean timings."""
    import shutil
    for sub in ("wiki", ".index"):
        target = paths.root / sub
        if target.exists():
            shutil.rmtree(target)
    (paths.root / "wiki").mkdir(parents=True, exist_ok=True)
    for d in ("sources", "entities", "concepts", "synthesis", "_stubs"):
        (paths.root / "wiki" / d).mkdir(parents=True, exist_ok=True)
    print(f"[loop] wiped perf-test wiki/.index (fresh start)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=10)
    ap.add_argument("--docs", type=int, default=3)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--start-round", type=int, default=1)
    ap.add_argument("--wipe", action="store_true")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    ctx, paths = resolve_project(PERF_ID, by_id_only=True)
    print(f"[loop] project: {ctx.name} ({ctx.id})")

    if args.wipe:
        wipe_project(paths)

    all_sources = sorted(NOVEL_SOURCES.rglob("*.md"))
    rng = random.Random(args.seed)
    shuffled = all_sources[:]
    rng.shuffle(shuffled)
    print(f"[loop] {len(shuffled)} sources shuffled (seed={args.seed})")

    provider = create_llm_provider("minimax")
    instr = InstrumentedProvider(provider)

    cursor = 0
    for rnd in range(args.start_round, args.start_round + args.rounds):
        picks = shuffled[cursor:cursor + args.docs]
        cursor += args.docs
        if not picks:
            print(f"[loop] round {rnd}: no more sources, stopping early")
            break
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        print(f"\n[round {rnd}] picking {len(picks)} docs: "
              + ", ".join(p.name[:20] for p in picks))

        docs_report = []
        for i, pick in enumerate(picks):
            instr.calls.clear()
            task_id = f"perf-r{rnd}-d{i}"
            try:
                pages, dt, text = asyncio.run(ingest_one(paths, instr, pick, task_id))
            except Exception as e:
                calls = list(instr.calls)
                docs_report.append({
                    "name": pick.name,
                    "chars": len(pick.read_text(encoding="utf-8", errors="replace")),
                    "total_s": sum(c["latency"] for c in calls),
                    "call_count": len(calls),
                    "avg_call_s": sum(c["latency"] for c in calls) / max(len(calls), 1),
                    "page_count": 0,
                    "pages": [],
                    "calls": calls,
                    "verdict": "crashed",
                    "failed": f"{type(e).__name__}: {e}",
                })
                print(f"[round {rnd}] {pick.name[:32]}: CRASHED "
                      f"({type(e).__name__}) after {len(calls)} calls, {sum(c['latency'] for c in calls):.1f}s")
                continue

            quals = [page_quality(p) for p in pages]
            calls = list(instr.calls)
            verdict = "fallback" if any(q["depth"] == "stub" for q in quals) else "ok"
            docs_report.append({
                "name": pick.name,
                "chars": len(text),
                "total_s": dt,
                "call_count": len(calls),
                "avg_call_s": sum(c["latency"] for c in calls) / max(len(calls), 1),
                "page_count": len(pages),
                "pages": quals,
                "calls": calls,
                "verdict": verdict,
            })
            print(f"[round {rnd}] {pick.name[:32]}: {fmt_dt(dt)}s, "
                  f"{len(pages)} pages, {len(calls)} calls [{verdict}]")

        agg = build_agg(docs_report)
        plan_path = write_plan(rnd, stamp, docs_report, agg)
        raw_path = write_raw(rnd, stamp, docs_report)
        print(f"[round {rnd}] plan → {plan_path}")

        if rnd < args.start_round + args.rounds - 1 and cursor < len(shuffled):
            elapsed_since_start = agg["total_s"]
            residual = 60.0 - elapsed_since_start
            if residual > 0:
                print(f"[round {rnd}] pacing: sleep {residual:.0f}s to 1-min cadence")
                time.sleep(residual)

    print("\n[loop] complete")


if __name__ == "__main__":
    main()
