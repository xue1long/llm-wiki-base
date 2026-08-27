"""A-1 KU dry-run 脚本（路线 v2.2 §A-1, F-3 整改 / H-5 ADR-002）.

F-3 决策要求：A-1 实际 backfill 前必须先做 dry-run.
本脚本**只生成报告，不实际修改 KnowledgeObject 或 WikiPage**.

扫描指定项目的 wiki 页面，输出:
1. PageType 分类统计 (ENTITY/CONCEPT/CLAIM/SYNTHESIS/DECISION/PROCEDURE/EVENT)
2. 叙述类页面 (CLAIM/SYNTHESIS/DECISION/PROCEDURE/EVENT) 长度分布
3. 抽样 20 个叙述类页面 (手工评估建议, 不评估)
4. backfill 成本估算 (复用 H-5 kc_ku_cost_estimator 的成本公式)

输出:
- Markdown 报告到 docs/migration/ku_dryrun_report.md (默认)
- JSON 输出到 docs/migration/ku_dryrun_report.json (--json-output)

用法:
    python scripts/kc_ku_dryrun.py --project-root <path>
    python scripts/kc_ku_dryrun.py --project-root knowledge/novel-wiki

参见:
    docs/adr/2026-08-26-ku-split-strategy.md
    docs/superpowers/plans/2026-08-26-kc-spec-roadmap.md §A-1 + F-3
    scripts/kc_ku_cost_estimator.py (H-5, 复用 cost 公式)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable

# Windows GBK 控制台下, ¥ 等字符会触发 UnicodeEncodeError.
# 强制 stdout 为 UTF-8 (PowerShell 7/Windows Terminal 已支持).
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover
        pass

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

# PageType 枚举 (与 src/wiki/core/types.py::PageType 对齐)
NARRATIVE_TYPES = {"claim", "synthesis", "decision", "procedure", "event"}
ENTITY_LIKE_TYPES = {"entity", "concept", "source"}

# 路线 §A-1 决策矩阵常量 (CNY 计价) - 与 H-5 kc_ku_cost_estimator 对齐
NARRATIVE_RATIO_UPPER = 0.40
PRECISION_RATIO = 0.10
PRECISION_RATIO_LOWER = 0.05
LLM_SPLIT_UNIT_COST_CNY = 0.5

# 抽样数 (F-3 整改要求)
SAMPLE_SIZE = 20


def _parse_frontmatter(text: str) -> dict:
    """提取 markdown 文件 frontmatter (YAML). 无 yaml 依赖时退化识别 type."""
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    fm_block = parts[1]
    if yaml is not None:
        try:
            data = yaml.safe_load(fm_block) or {}
            return data if isinstance(data, dict) else {}
        except yaml.YAMLError:
            return {}
    out: dict = {}
    m = re.search(r"^type:\s*(\S+)\s*$", fm_block, re.MULTILINE)
    if m:
        out["type"] = m.group(1)
    return out


def _find_wiki_root(project_root: Path) -> Path | None:
    """定位项目内的 wiki/ 目录.

    支持两种布局:
      <root>/wiki/**/*.md
      <root>/<project_id>/wiki/**/*.md  (multi-project 布局)
    """
    direct = project_root / "wiki"
    if direct.is_dir():
        return direct
    for sub in project_root.iterdir():
        if sub.is_dir() and (sub / "wiki").is_dir():
            return sub / "wiki"
    return None


def scan_pages(wiki_root: Path) -> list[dict]:
    """扫描 wiki/**.md, 返回每个页面的元数据列表.

    每个元素: {"path": Path, "type": str, "body": str, "token_count": int}
    """
    pages: list[dict] = []
    if not wiki_root.exists():
        return pages
    for path in wiki_root.rglob("*.md"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        meta = _parse_frontmatter(text)
        t = str(meta.get("type", "unknown")).lower().strip() or "unknown"
        # 估算 body token 数 (中文按字符, 英文按空白分词)
        body = text.split("---", 2)[2] if text.startswith("---") else text
        token_count = _approx_token_count(body)
        pages.append({
            "path": path,
            "type": t,
            "body": body,
            "token_count": token_count,
        })
    return pages


def _approx_token_count(body: str) -> int:
    """粗略估算 token 数: 中文字符按 1 token, 英文按空白分词."""
    # 移除 markdown 标记 (简化版)
    text = re.sub(r"[#*`_>\[\]\(\)]", " ", body)
    # 中文每个字符算 1 token
    cn_chars = re.findall(r"[\u4e00-\u9fff]", text)
    # 英文按空白分词
    en_words = re.findall(r"[a-zA-Z0-9]+", text)
    return len(cn_chars) + len(en_words)


def summarize_pages(pages: list[dict]) -> dict:
    """汇总页面数据为统计字典.

    Returns: {
        "page_type_distribution": {"concept": N, "entity": N, ...},
        "narrative_pages": N,
        "narrative_length_distribution": {
            "min": N, "max": N, "avg": N, "median": N
        },
        "narrative_sample_paths": [str, str, ...] (up to SAMPLE_SIZE)
    }
    """
    dist: dict[str, int] = {}
    narrative_paths: list[str] = []
    narrative_tokens: list[int] = []
    for page in pages:
        t = page["type"]
        dist[t] = dist.get(t, 0) + 1
        if t in NARRATIVE_TYPES:
            narrative_paths.append(str(page["path"]))
            narrative_tokens.append(page["token_count"])

    narrative_paths_sorted = sorted(narrative_paths)
    sample = narrative_paths_sorted[:SAMPLE_SIZE]

    length_dist: dict[str, float | int] = {}
    if narrative_tokens:
        sorted_tokens = sorted(narrative_tokens)
        n = len(sorted_tokens)
        median = (
            sorted_tokens[n // 2]
            if n % 2 == 1
            else (sorted_tokens[n // 2 - 1] + sorted_tokens[n // 2]) // 2
        )
        length_dist = {
            "min": sorted_tokens[0],
            "max": sorted_tokens[-1],
            "avg": round(sum(sorted_tokens) / n, 1),
            "median": median,
            "count": n,
        }

    return {
        "page_type_distribution": dist,
        "narrative_pages": len(narrative_paths),
        "narrative_length_distribution": length_dist,
        "narrative_sample_paths": sample,
    }


def estimate_costs(page_type_counts: dict[str, int]) -> dict:
    """成本估算 (复用 H-5 公式)."""
    wiki_pages = sum(v for k, v in page_type_counts.items() if k != "unknown")
    unknown = page_type_counts.get("unknown", 0)
    observed_narrative = sum(
        v for k, v in page_type_counts.items() if k in NARRATIVE_TYPES
    )
    estimated_narrative = round(wiki_pages * NARRATIVE_RATIO_UPPER)

    # choice_1: 不拆
    choice_1_cost = 0
    # choice_2: 所有叙事类都拆 (取上限)
    narrative_for_choice_2 = max(observed_narrative, estimated_narrative)
    choice_2_cost = round(narrative_for_choice_2 * LLM_SPLIT_UNIT_COST_CNY)
    # choice_3: 仅 precision_ratio 比例拆
    precision_mid = (PRECISION_RATIO_LOWER + PRECISION_RATIO) / 2
    narrative_for_choice_3_low = round(observed_narrative * PRECISION_RATIO_LOWER)
    narrative_for_choice_3_high = round(observed_narrative * PRECISION_RATIO)
    narrative_for_choice_3 = max(narrative_for_choice_3_low, narrative_for_choice_3_high)
    choice_3_cost = round(narrative_for_choice_3 * LLM_SPLIT_UNIT_COST_CNY)

    return {
        "wiki_pages": wiki_pages,
        "unknown_pages": unknown,
        "narrative_pages": observed_narrative,
        "narrative_pages_estimated_upper": estimated_narrative,
        "choice_1_cost": choice_1_cost,
        "choice_2_cost": choice_2_cost,
        "choice_3_cost": choice_3_cost,
        "precision_ratio": PRECISION_RATIO,
        "llm_split_unit_cost_cny": LLM_SPLIT_UNIT_COST_CNY,
        "recommendation": "choice_3",
    }


def render_markdown_report(report: dict, project_root: Path) -> str:
    """渲染 Markdown 报告."""
    lines: list[str] = []
    lines.append("# A-1 KU Dry-Run 报告（路线 §A-1, F-3 整改 / H-5 ADR-002）")
    lines.append("")
    lines.append(f"- 项目根: `{project_root}`")
    lines.append(f"- wiki 页面总数: **{report['wiki_pages']}**")
    lines.append(f"  - 其中 unknown (无 frontmatter / 无 type 字段): {report['unknown_pages']}")
    lines.append(f"- 叙述类页面 (CLAIM/SYNTHESIS/DECISION/PROCEDURE/EVENT): **{report['narrative_pages']}**")
    lines.append(f"- 叙述类估算上限 (40%): {report['narrative_pages_estimated_upper']}")
    lines.append("")
    lines.append("## 1. PageType 分布")
    lines.append("")
    lines.append("| PageType | 数量 |")
    lines.append("|---|---|")
    for k, v in sorted(report["page_type_distribution"].items()):
        lines.append(f"| {k} | {v} |")
    lines.append("")
    lines.append("## 2. 叙述类页面长度分布")
    lines.append("")
    ld = report["narrative_length_distribution"]
    if ld:
        lines.append("| 指标 | 值 |")
        lines.append("|---|---|")
        lines.append(f"| 数量 | {ld['count']} |")
        lines.append(f"| 最短 (tokens) | {ld['min']} |")
        lines.append(f"| 最长 (tokens) | {ld['max']} |")
        lines.append(f"| 平均 (tokens) | {ld['avg']} |")
        lines.append(f"| 中位 (tokens) | {ld['median']} |")
    else:
        lines.append("(无叙述类页面)")
    lines.append("")
    lines.append("## 3. 抽样 20 个叙述类页面（手工评估建议）")
    lines.append("")
    lines.append("> ⚠️ **本脚本仅提示抽样清单，不做评估**. 由人工按 H-5 ADR-002 §\"答案不明确的判定规则\" 评估.")
    lines.append("")
    samples = report["narrative_sample_paths"]
    if samples:
        for i, p in enumerate(samples, 1):
            lines.append(f"{i}. `{p}`")
    else:
        lines.append("(无叙述类页面可抽样)")
    lines.append("")
    lines.append("## 4. Backfill 成本估算（与 H-5 一致）")
    lines.append("")
    lines.append("| 选择 | 描述 | 成本 (CNY) |")
    lines.append("|---|---|---|")
    lines.append(
        f"| choice_1 | 不拆 | {report['choice_1_cost']} CNY |"
    )
    lines.append(
        f"| choice_2 | 长叙事类 (>5 段) 全量 LLM 拆分 | {report['choice_2_cost']} CNY |"
    )
    lines.append(
        f"| choice_3 | 仅\"答案不明确\"页面 LLM 拆分 | {report['choice_3_cost']} CNY |"
    )
    lines.append("")
    lines.append(f"**默认 = `{report['recommendation']}`** （H-5 ADR-002 推荐）")
    lines.append("")
    if report["choice_3_cost"] < report["choice_2_cost"]:
        saving = report["choice_2_cost"] - report["choice_3_cost"]
        saving_pct = (
            round(100 * saving / report["choice_2_cost"])
            if report["choice_2_cost"] > 0
            else 0
        )
        lines.append(
            f"choice_3 比 choice_2 节省: **{saving} CNY ({saving_pct}%)**"
        )
    lines.append("")
    lines.append("## 5. 下一步")
    lines.append("")
    lines.append("- [ ] 用户在 3 个自然日内决策 choice_1/2/3 (H-5 ADR-002 §Decision)")
    lines.append("- [ ] 超时 → 自动采用 choice_3 (H-5 ADR-002 §Decision)")
    lines.append("- [ ] 决策后由 A-1 主任务执行实际 backfill")
    lines.append("")
    lines.append("## 参考")
    lines.append("")
    lines.append("- `docs/adr/2026-08-26-ku-split-strategy.md` (H-5 ADR)")
    lines.append("- `docs/superpowers/plans/2026-08-26-kc-spec-roadmap.md` §A-1 + F-3")
    lines.append("- `scripts/kc_ku_cost_estimator.py` (H-5 成本公式来源)")
    return "\n".join(lines)


def run_dryrun(project_root: Path) -> dict:
    """执行 dry-run: 扫描 + 统计 + 估算. 返回完整 report dict."""
    wiki_root = _find_wiki_root(project_root)
    if wiki_root is None:
        return {"error": f"wiki/ directory not found under {project_root}"}
    pages = scan_pages(wiki_root)
    summary = summarize_pages(pages)
    costs = estimate_costs(summary["page_type_distribution"])
    # 合并 summary + costs
    return {**summary, **costs}


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="A-1 KU dry-run 脚本（路线 §A-1, F-3 整改）"
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path("."),
        help="项目根路径（含 wiki/ 子目录或 <id>/wiki/ 子目录）",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Markdown 输出路径（默认: docs/migration/ku_dryrun_report.md）",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=None,
        help="JSON 输出路径（默认: 与 --output 同名 .json）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="输出 JSON 到 stdout（仅调试用）",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    project_root: Path = args.project_root.resolve()
    if not project_root.exists():
        print(f"ERROR: project not found: {project_root}", file=sys.stderr)
        return 1

    report = run_dryrun(project_root)
    if "error" in report:
        print(f"ERROR: {report['error']}", file=sys.stderr)
        return 1

    # 默认输出路径
    if args.output is None:
        # 写入 docs/migration/ku_dryrun_report.md (项目根的 docs/migration/)
        default_dir = project_root / "docs" / "migration"
        args.output = default_dir / "ku_dryrun_report.md"
    if args.json_output is None:
        args.json_output = args.output.with_suffix(".json")

    # 写 Markdown
    md = render_markdown_report(report, project_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(md, encoding="utf-8")
    # 写 JSON
    json_payload = json.dumps(report, ensure_ascii=False, indent=2)
    args.json_output.write_text(json_payload, encoding="utf-8")

    if args.json:
        print(json_payload)
    else:
        print(f"Markdown 报告: {args.output}")
        print(f"JSON 报告:     {args.json_output}")
        print(f"叙述类页面数: {report['narrative_pages']}")
        print(f"cost_1 / cost_2 / cost_3: "
              f"{report['choice_1_cost']} / "
              f"{report['choice_2_cost']} / "
              f"{report['choice_3_cost']} CNY")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())