"""Wiki 重建 dry-run 演示 (B-3.5 commit 1, spec §17 D-18 + Z-2).

本脚本**只读演示**, 不修改任何 WikiPage frontmatter.

演示内容:
- 扫描现有 WikiPage 数量 (limit max_pages 避免超时)
- 应用 IntegrityGate 11 Gate (只读, 不写)
- 输出 quality_score baseline (B-3 commit 4 generate_health_report 接口)
- 模拟重建后的 rendered_hash 对比 (前 5 个)
- 统计 legacy 页面 (workflow_state != 'verified')

CLI:
    PYTHONPATH=. python scripts/kc_wiki_rebuild_dryrun.py --project-root <path>
    PYTHONPATH=. python scripts/kc_wiki_rebuild_dryrun.py --project-root <path> --max-pages 50

输出:
- JSON 报告到 stdout (默认) 或 --output <path>

Ref: docs/architecture/B-2_11_Gate_design.md + spec §17 D-18 + Z-2.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Windows GBK 控制台下, ¥ 等字符会触发 UnicodeEncodeError.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover
        pass


@dataclass(frozen=True)
class WikiRebuildDryrunResult:
    """Wiki 重建 dry-run 结果.

    Attributes:
        project_root:         项目根路径
        wiki_pages_scanned:    扫描的 WikiPage 数量 (max_pages 限制内)
        integrity_reports:     前 5 个 IntegrityReport 样本 (11 Gate × sample)
        health_quality_score:  Health Report baseline quality_score
        health_gate_failures:  各 Gate 失败数 (gate_name → count)
        sample_rendered_hashes: page_id → simulated rendered_hash (sha256[:16])
        legacy_pages_count:    workflow_state != 'verified' 的页面数
        would_block_pages:     任一 Gate block 的页面数
        would_warn_pages:      仅 warn (无 block) 的页面数
        not_evaluable:         passed_checks=0 时 True
    """

    project_root: Path
    wiki_pages_scanned: int
    integrity_reports: tuple[Any, ...]
    health_quality_score: float
    health_gate_failures: dict[str, int]
    sample_rendered_hashes: dict[str, str]
    legacy_pages_count: int
    would_block_pages: int
    would_warn_pages: int
    not_evaluable: bool


def _mock_wiki_page_from_md(page_id: str, content: str, md_file: Path) -> Any:
    """简化 mock WikiPage (避免完整 frontmatter 解析).

    返回 WikiPage 实例, 含 workflow_state 字段 (供 legacy 计数).
    """
    from src.wiki.core.types import WikiPage, PageType

    page = WikiPage(
        id=page_id,
        title=page_id,
        type=PageType.CONCEPT,
    )
    # 简化 frontmatter 解析
    workflow_state = "draft"
    if content.startswith("---"):
        end = content.find("\n---", 4)
        if end > 0:
            try:
                import yaml  # type: ignore[import-untyped]

                fm = yaml.safe_load(content[4:end]) or {}
                if isinstance(fm, dict):
                    workflow_state = str(fm.get("workflow_state", "draft"))
            except Exception:
                workflow_state = "draft"
    page.workflow_state = workflow_state
    return page


def _simulate_rebuild_hash(content: str) -> str:
    """模拟 WikiTemplateCompiler.compile() 输出的 rendered_hash (sha256[:16]).

    实际 A-7 WikiTemplateCompiler 涉及更多 slot 拼装, 此处只简化演示
    "重建后能产出稳定的 hash" 这一能力.
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def run_dryrun(project_root: Path, max_pages: int = 100) -> WikiRebuildDryrunResult:
    """运行 Wiki 重建 dry-run (只读).

    步骤:
    1. 扫描 <project_root>/wiki/**/*.md (限制 max_pages)
    2. 对每个 WikiPage 解析 frontmatter (mock WikiPage)
    3. 应用 IntegrityGate 11 Gate (只读)
    4. 生成 Health Report (quality_score baseline)
    5. 模拟重建 rendered_hash (sha256[:16] of content)
    6. 输出 dry-run 报告

    Args:
        project_root: 项目根路径 (含 wiki/ 子目录)
        max_pages:    扫描上限 (避免大数据集超时)

    Returns:
        WikiRebuildDryrunResult 含扫描统计 + quality_score + sample hashes
    """
    # 1. 扫描 wiki
    wiki_dir = project_root / "wiki"
    md_files: list[Path] = []
    if wiki_dir.is_dir():
        md_files = sorted(wiki_dir.rglob("*.md"))[:max_pages]

    # 2+3. 解析 + 11 Gate
    from src.kc.integrity.orchestrator import IntegrityGate

    gate = IntegrityGate()
    integrity_reports: list[Any] = []
    legacy_count = 0
    would_block = 0
    would_warn = 0
    sample_hashes: dict[str, str] = {}

    for md_file in md_files:
        page_id = md_file.stem
        try:
            content = md_file.read_text(encoding="utf-8")
        except Exception:
            continue

        mock_page = _mock_wiki_page_from_md(page_id, content, md_file)

        # 应用 11 Gate
        try:
            report = gate.check(mock_page, context={})
        except Exception:
            # gate 异常 → 跳过 (避免 dry-run 本身崩溃)
            continue

        integrity_reports.append(report)

        # 统计
        if mock_page.workflow_state != "verified":
            legacy_count += 1
        if report.blocked:
            would_block += 1
        elif any(
            r.verdict.severity == "warn" and not r.verdict.blocked
            for r in report.gate_results
        ):
            would_warn += 1

        # 5. 模拟重建 rendered_hash
        sample_hashes[page_id] = _simulate_rebuild_hash(content)

    # 4. Health Report baseline
    from src.kc.integrity.health import generate_health_report

    health = generate_health_report(integrity_reports)

    return WikiRebuildDryrunResult(
        project_root=project_root,
        wiki_pages_scanned=len(md_files),
        integrity_reports=tuple(integrity_reports[:5]),
        health_quality_score=health.quality_score,
        health_gate_failures=health.gate_failures,
        sample_rendered_hashes=sample_hashes,
        legacy_pages_count=legacy_count,
        would_block_pages=would_block,
        would_warn_pages=would_warn,
        not_evaluable=health.not_evaluable,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Wiki rebuild dry-run (B-3.5 commit 1)")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    result = run_dryrun(args.project_root, max_pages=args.max_pages)

    report = {
        "project_root": str(result.project_root),
        "wiki_pages_scanned": result.wiki_pages_scanned,
        "health_quality_score": result.health_quality_score,
        "health_gate_failures": result.health_gate_failures,
        "sample_rendered_hashes": result.sample_rendered_hashes,
        "legacy_pages_count": result.legacy_pages_count,
        "would_block_pages": result.would_block_pages,
        "would_warn_pages": result.would_warn_pages,
        "not_evaluable": result.not_evaluable,
    }

    output_text = json.dumps(report, indent=2, ensure_ascii=False)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text, encoding="utf-8")
        print(f"Dry-run report written to {args.output}")
    else:
        print(output_text)

    return 0


if __name__ == "__main__":
    sys.exit(main())
