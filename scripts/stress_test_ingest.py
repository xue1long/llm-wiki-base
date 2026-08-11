"""Stress test + quality audit for LLM-Wiki batch ingest pipeline.

10 rounds, 3 random documents each. Observes quality + speed, writes
optimization proposals to out/plans/round_<i>_<timestamp>.md.
"""
import asyncio
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Fix Windows GBK encoding issues
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

from src.pipeline.ingest import run_ingest
from src.wiki.core.paths import WikiPaths
from src.llm.provider_factory import create_llm_provider
from src.llm.registry import ProviderRegistry

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
NOVEL_WIKI = PROJECT_ROOT / "knowledge" / "novel-wiki"
RAW_SOURCES = NOVEL_WIKI / "raw" / "sources"
PATHS = WikiPaths(NOVEL_WIKI)
OUT_DIR = PROJECT_ROOT / "out" / "plans"
OUT_DIR.mkdir(parents=True, exist_ok=True)

MIN_DOC_BYTES = 500
MAX_DOC_BYTES = 30_000  # smaller docs for faster testing
INGEST_TIMEOUT = 300.0  # seconds per document (observed ~110s for 3.6KB)
ROUNDS = 10
DOCS_PER_ROUND = 3


def pick_random_docs(n: int) -> list[Path]:
    """Pick n random documents from the raw sources pool."""
    pool = []
    for f in RAW_SOURCES.rglob("*"):
        if f.is_file() and f.suffix in (".md", ".txt"):
            size = f.stat().st_size
            if MIN_DOC_BYTES <= size <= MAX_DOC_BYTES:
                pool.append(f)
    return random.sample(pool, min(n, len(pool)))


def summarize_pages(pages) -> dict:
    """Extract summary stats from a list of WikiPages."""
    by_type: dict[str, int] = {}
    by_grade: dict[str, int] = {}
    total_body_chars = 0
    for p in pages:
        pt = p.type.value if hasattr(p.type, "value") else str(p.type)
        by_type[pt] = by_type.get(pt, 0) + 1
        g = getattr(p, "grade", "B") or "B"
        by_grade[g] = by_grade.get(g, 0) + 1
        total_body_chars += len(getattr(p, "body", "") or "")
    return {
        "total": len(pages),
        "by_type": by_type,
        "by_grade": by_grade,
        "avg_body_chars": total_body_chars // max(len(pages), 1),
    }


async def ingest_one(doc_path: Path, provider) -> dict:
    """Ingest a single document. Returns timing + result dict."""
    started = time.time()
    source_text = doc_path.read_text(encoding="utf-8")
    doc_size = len(source_text.encode("utf-8"))
    task_id = f"stress-{int(started * 1000)}"

    try:
        pages = await asyncio.wait_for(
            run_ingest(
                paths=PATHS,
                source_path=doc_path,
                source_text=source_text,
                provider=provider,
                task_id=task_id,
            ),
            timeout=INGEST_TIMEOUT,
        )
        elapsed = time.time() - started
        return {
            "doc": str(doc_path.relative_to(NOVEL_WIKI)),
            "doc_name": doc_path.name,
            "doc_bytes": doc_size,
            "elapsed_s": round(elapsed, 2),
            "pages": summarize_pages(pages),
            "error": None,
        }
    except asyncio.TimeoutError:
        return {
            "doc": str(doc_path.relative_to(NOVEL_WIKI)),
            "doc_name": doc_path.name,
            "doc_bytes": doc_size,
            "elapsed_s": round(time.time() - started, 2),
            "pages": None,
            "error": f"timeout after {INGEST_TIMEOUT}s",
        }
    except Exception as exc:
        return {
            "doc": str(doc_path.relative_to(NOVEL_WIKI)),
            "doc_name": doc_path.name,
            "doc_bytes": doc_size,
            "elapsed_s": round(time.time() - started, 2),
            "pages": None,
            "error": f"{type(exc).__name__}: {exc}",
        }


def write_proposal(round_num: int, docs: list[Path], results: list[dict], round_start: float) -> Path:
    """Write optimization proposal markdown file."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"round_{round_num:02d}_{timestamp}.md"
    out = OUT_DIR / filename

    total_elapsed = time.time() - round_start
    success = [r for r in results if r["error"] is None]
    failed = [r for r in results if r["error"] is not None]
    total_pages = sum(r["pages"]["total"] for r in success) if success else 0

    lines = [
        f"# 摄取压力测试 — 第 {round_num} 轮",
        f"",
        f"**时间**: {timestamp}  ",
        f"**耗时**: {total_elapsed:.1f}s  ",
        f"**文档数**: {len(docs)} (成功 {len(success)}, 失败 {len(failed)})  ",
        f"**生成页面**: {total_pages}  ",
        f"",
        "---",
        f"",
        f"## 1. 本轮文档",
        f"",
    ]

    for i, doc in enumerate(docs):
        size_kb = doc.stat().st_size / 1024
        lines.append(f"{i+1}. `{doc.relative_to(NOVEL_WIKI)}` ({size_kb:.0f} KB)")

    lines += [
        "",
        "---",
        "",
        "## 2. 摄取结果",
        "",
    ]

    for i, r in enumerate(results):
        lines.append(f"### 2.{i+1}. {r['doc_name']}")
        lines.append(f"")
        lines.append(f"| 指标 | 值 |")
        lines.append(f"|------|-----|")
        lines.append(f"| 文档大小 | {r['doc_bytes']:,} bytes |")
        lines.append(f"| 耗时 | {r['elapsed_s']:.1f}s |")
        if r["error"]:
            lines.append(f"| 错误 | {r['error']} |")
        else:
            pg = r["pages"]
            lines.append(f"| 生成页面数 | {pg['total']} |")
            lines.append(f"| 页面类型分布 | {pg['by_type']} |")
            lines.append(f"| Grade 分布 | {pg['by_grade']} |")
            lines.append(f"| 平均 body 长度 | {pg['avg_body_chars']} chars |")
            if pg["total"] > 0:
                throughput = r["doc_bytes"] / r["elapsed_s"] if r["elapsed_s"] > 0 else 0
                lines.append(f"| 吞吐量 | {throughput:.0f} bytes/s |")
        lines.append("")

    lines += [
        "---",
        "",
        "## 3. 质量分析",
        "",
    ]

    # Quality observations
    quality_issues = []
    speed_issues = []

    for r in results:
        if r["error"]:
            quality_issues.append(f"- **{r['doc_name']}**: 摄取失败 — {r['error']}")
            speed_issues.append(f"- **{r['doc_name']}**: {r['error']}")

    for r in success:
        pg = r["pages"]
        name = r["doc_name"]

        # Check for low page counts
        if pg["total"] == 0:
            quality_issues.append(f"- **{name}**: 零页面产出（可能被 Reviewer 拒绝或 LLM 返回空）")
        elif pg["total"] == 1 and pg["by_type"].get("source", 0) == 1:
            quality_issues.append(f"- **{name}**: 仅产出 source 页，无实体/概念抽取")
        elif pg["total"] < 3:
            quality_issues.append(f"- **{name}**: 低产出 ({pg['total']} 页)")

        # Check for C-grade pages
        if pg["by_grade"].get("C", 0) > 0:
            quality_issues.append(f"- **{name}**: {pg['by_grade']['C']} 个 C 级页面（质量警告）")

        # Check body length
        if pg["avg_body_chars"] < 200:
            quality_issues.append(f"- **{name}**: 平均 body 长度仅 {pg['avg_body_chars']} 字符，内容偏薄")

        # Speed: slow docs
        if r["elapsed_s"] > 60:
            speed_issues.append(f"- **{name}**: 耗时 {r['elapsed_s']:.0f}s，超过 60s 阈值")
        elif r["elapsed_s"] > 30:
            speed_issues.append(f"- **{name}**: 耗时 {r['elapsed_s']:.0f}s，接近瓶颈")

        # Speed: bytes/sec
        throughput = r["doc_bytes"] / r["elapsed_s"] if r["elapsed_s"] > 0 else 0
        if throughput < 1000 and r["doc_bytes"] > 5000:
            speed_issues.append(f"- **{name}**: 吞吐量仅 {throughput:.0f} bytes/s")

    if quality_issues:
        lines += quality_issues
    else:
        lines.append("本轮未发现显著质量问题。")

    lines += [
        "",
        "---",
        "",
        "## 4. 速度分析",
        "",
        f"| 指标 | 值 |",
        f"|------|-----|",
        f"| 总耗时 | {total_elapsed:.1f}s |",
        f"| 成功文档数 | {len(success)} |",
    ]
    if success:
        avg_time = sum(r["elapsed_s"] for r in success) / len(success)
        total_bytes = sum(r["doc_bytes"] for r in success)
        lines += [
            f"| 平均单文档耗时 | {avg_time:.1f}s |",
            f"| 总处理字节数 | {total_bytes:,} |",
            f"| 总体吞吐量 | {total_bytes / total_elapsed:.0f} bytes/s |",
        ]

    lines.append("")

    if speed_issues:
        lines += speed_issues
    else:
        lines.append("本轮未发现显著速度瓶颈。")

    lines += [
        "",
        "---",
        "",
        "## 5. 优化建议",
        "",
    ]

    # Generate contextual recommendations based on observations
    rec_idx = 1
    if failed:
        lines.append(f"### 稳定性")
        lines.append(f"")
        for f_r in failed:
            lines.append(f"{rec_idx}. **处理 {f_r['doc_name']} 的失败**: {f_r['error']}。建议增加重试逻辑或超时后降级为 source-only 页面。")
            rec_idx += 1
        lines.append("")

    if any(r["elapsed_s"] > 60 for r in success):
        lines.append(f"### 速度优化")
        lines.append(f"")
        slow_docs = [r for r in success if r["elapsed_s"] > 60]
        avg_slow = sum(r["elapsed_s"] for r in slow_docs) / len(slow_docs)
        lines.append(f"{rec_idx}. **长文档处理**: {len(slow_docs)} 个文档超过 60s（平均 {avg_slow:.0f}s）。建议：")
        lines.append(f"   - 对 > 50KB 文档启用 chunked 模式（当前阈值 12KB 偏低，可能产生过量分块）")
        lines.append(f"   - 增加 analyzer 并发度（当前串行处理所有 chunk）")
        rec_idx += 1

    if total_elapsed > 120:
        lines.append(f"{rec_idx}. **批量并行化**: 3 文档总耗时 {total_elapsed:.0f}s，串行吞吐量偏低。建议 `run_batch_ingest` 默认并发度从 3 提升至 5，或按文档大小动态调整。")
        rec_idx += 1

    low_page_docs = [r for r in success if r["pages"]["total"] < 3]
    if low_page_docs:
        lines.append(f"### 质量优化")
        lines.append(f"")
        lines.append(f"{rec_idx}. **低产文档**: {len(low_page_docs)} 个文档产出 < 3 页。建议：")
        lines.append(f"   - 对产出 < 2 页的文档，自动触发 re-analysis（不同 prompt 变体）")
        lines.append(f"   - 分析这些文档的共同特征（过短？格式差？领域不匹配？）")
        rec_idx += 1

    c_grade_docs = [r for r in success if r["pages"]["by_grade"].get("C", 0) > 0]
    if c_grade_docs:
        lines.append(f"{rec_idx}. **C 级页面**: {len(c_grade_docs)} 个文档产生 C 级页面。建议对 C 级页面增加自动 re-generate 或标记为 stub。")
        rec_idx += 1

    # Always add some general recommendations after round 3+
    if round_num >= 3:
        lines.append(f"### 累积优化建议（基于前 {round_num} 轮）")
        lines.append(f"")
        lines.append(f"{rec_idx}. **可观测性**: 已产出 ingest_reports，建议在 `/metrics` 端点增加 P50/P95/P99 延迟直方图。")
        rec_idx += 1
        lines.append(f"{rec_idx}. **文档筛选**: 前 {round_num} 轮共处理 {round_num * DOCS_PER_ROUND} 个文档，可聚类分析哪些文档类型（长度/领域/格式）产生最佳摄取质量。")
        rec_idx += 1
        lines.append(f"{rec_idx}. **缓存策略**: 对相似文档(如<入门教程>系列), LLM 分析结果存在大量重复。建议增加语义缓存层(相似文档 -> 复用 analysis skeleton)。")
        rec_idx += 1

    lines += [
        "",
        "---",
        "",
        f"*由 stress_test_ingest.py 自动生成 — 第 {round_num}/10 轮*",
    ]

    out.write_text("\n".join(lines), encoding="utf-8")
    return out


async def run_round(round_num: int, provider) -> Path:
    """Execute one stress test round."""
    docs = pick_random_docs(DOCS_PER_ROUND)
    round_start = time.time()

    print(f"\n{'='*60}")
    print(f"ROUND {round_num}/10 — {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*60}")
    for i, doc in enumerate(docs):
        print(f"  [{i+1}] {doc.name} ({doc.stat().st_size / 1024:.0f} KB)")
    print()

    results = []
    for i, doc in enumerate(docs):
        print(f"  Ingesting [{i+1}/{len(docs)}]: {doc.name} ...", end=" ", flush=True)
        result = await ingest_one(doc, provider)
        if result["error"]:
            print(f"FAILED: {result['error']}")
        else:
            pg = result["pages"]
            print(f"OK — {pg['total']} pages, {pg['by_type']}, {result['elapsed_s']:.1f}s")
        results.append(result)

    proposal_path = write_proposal(round_num, docs, results, round_start)
    print(f"\n  Proposal → {proposal_path.name}")
    return proposal_path


async def main():
    print("=" * 60)
    print("LLM-Wiki 摄取压力测试 + 质量审计")
    print(f"文档池: {RAW_SOURCES}")
    print(f"轮次: {ROUNDS}, 每轮文档: {DOCS_PER_ROUND}")
    print(f"输出: {OUT_DIR}")
    print("=" * 60)

    # Build provider once
    try:
        provider = create_llm_provider("minimax")
        print("LLM provider: minimax ✓")
    except Exception as exc:
        print(f"LLM provider failed: {exc}")
        print("Trying fallback to default...")
        provider = create_llm_provider(
            ProviderRegistry.get_default().name
        )
        print(f"LLM provider: {ProviderRegistry.get_default().name}")

    for r in range(1, ROUNDS + 1):
        try:
            await run_round(r, provider)
        except Exception as exc:
            print(f"\n  Round {r} crashed: {exc}")
            # Write emergency report
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            crash_path = OUT_DIR / f"round_{r:02d}_{timestamp}_CRASH.md"
            crash_path.write_text(
                f"# Round {r} — CRASH\n\n**Error**: {type(exc).__name__}: {exc}\n",
                encoding="utf-8",
            )
            print(f"  Emergency report → {crash_path.name}")

        if r < ROUNDS:
            wait = 60
            print(f"\n  Waiting {wait}s until next round...")
            await asyncio.sleep(wait)

    print(f"\n{'='*60}")
    print(f"ALL {ROUNDS} ROUNDS COMPLETE")
    print(f"Reports → {OUT_DIR}")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
