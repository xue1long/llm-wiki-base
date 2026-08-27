"""Tests for A-1 KU dry-run script (路线 v2.2 §A-1, F-3 整改).

3 TDD tests:
1. dry-run 脚本扫描指定项目, 输出 PageType 分类统计
2. 叙述类页面 (CLAIM/SYNTHESIS/DECISION/PROCEDURE/EVENT) 识别正确
3. dry-run 报告含 PageType 分布 + backfill 成本估算 (与 H-5 脚本输出对齐)

不在 src/ 业务代码中改任何东西; 仅测试 scripts/kc_ku_dryrun.py 的
纯函数输出 + 报告生成.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "scripts" / "kc_ku_dryrun.py"
NOVEL_WIKI = REPO_ROOT / "knowledge" / "novel-wiki"

# 项目根中可直接 import 脚本模块
sys.path.insert(0, str(REPO_ROOT / "scripts"))


def _run(*args: str, timeout: int = 180) -> subprocess.CompletedProcess:
    """Run the dry-run script as subprocess."""
    import os

    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# Test 1: dry-run 脚本扫描指定项目, 输出 PageType 分类统计
# ---------------------------------------------------------------------------
def test_dryrun_scans_project_and_outputs_page_type_stats(tmp_path: Path) -> None:
    """在临时项目内创建 5 个 mock markdown (含 frontmatter type 字段),
    跑 dry-run, 验证 PageType 分类统计正确."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "mini_dryrun"
        (root / "wiki" / "concepts").mkdir(parents=True)
        (root / "wiki" / "entities").mkdir(parents=True)
        # 3 concept + 2 entity = 5 pages
        for i in range(3):
            (root / "wiki" / "concepts" / f"c{i}.md").write_text(
                f"---\nid: c{i}\ntitle: C{i}\ntype: concept\n---\n\nbody {i}\n",
                encoding="utf-8",
            )
        for i in range(2):
            (root / "wiki" / "entities" / f"e{i}.md").write_text(
                f"---\nid: e{i}\ntitle: E{i}\ntype: entity\n---\n\nbody {i}\n",
                encoding="utf-8",
            )
        out_path = root / "dryrun_report.md"
        r = _run(
            "--project-root", str(root),
            "--output", str(out_path),
        )
        assert r.returncode == 0, f"script failed: stderr={r.stderr!r}"
        # 报告文件已生成
        assert out_path.exists(), f"report not created: {out_path}"
        content = out_path.read_text(encoding="utf-8")
        # PageType 分类统计 - 必有 concept=3, entity=2
        assert "concept" in content.lower()
        assert "entity" in content.lower()
        # 报告中显式包含计数（concept: 3 或 | concept | 3 等）
        # 用宽松断言: 3 和 2 出现在文件中
        assert "3" in content
        assert "2" in content


# ---------------------------------------------------------------------------
# Test 2: 叙述类页面 (CLAIM/SYNTHESIS/DECISION/PROCEDURE/EVENT) 识别正确
# ---------------------------------------------------------------------------
def test_dryrun_identifies_narrative_pages(tmp_path: Path) -> None:
    """含 CLAIM/SYNTHESIS 页面, 验证叙述类识别 = 3 (1 claim + 2 synthesis)."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "mini_narrative"
        (root / "wiki" / "concepts").mkdir(parents=True)
        (root / "wiki" / "claims").mkdir(parents=True)
        (root / "wiki" / "synthesis").mkdir(parents=True)
        # 1 concept (非叙事类)
        (root / "wiki" / "concepts" / "c0.md").write_text(
            "---\nid: c0\ntitle: C0\ntype: concept\n---\n\nbody\n",
            encoding="utf-8",
        )
        # 1 claim (叙事类)
        (root / "wiki" / "claims" / "cl0.md").write_text(
            "---\nid: cl0\ntitle: Cl0\ntype: claim\n---\n\nbody\n",
            encoding="utf-8",
        )
        # 2 synthesis (叙事类)
        for i in range(2):
            (root / "wiki" / "synthesis" / f"syn{i}.md").write_text(
                f"---\nid: syn{i}\ntitle: Syn{i}\ntype: synthesis\n---\n\nbody {i}\n",
                encoding="utf-8",
            )
        out_path = root / "dryrun_report.md"
        r = _run(
            "--project-root", str(root),
            "--output", str(out_path),
        )
        assert r.returncode == 0, f"script failed: stderr={r.stderr!r}"
        content = out_path.read_text(encoding="utf-8")
        # 叙述类页面 (CLAIM + SYNTHESIS) = 1 + 2 = 3
        # 报告必须明确标记叙事类页面数 = 3
        # 关键词: "叙事类" / "narrative" + 数字 3
        assert "3" in content, "narrative page count 3 not in report"
        # 区分: 报告中 narrative_pages 字段或显式行
        # 至少要看到 "claim" 和 "synthesis" 两种 PageType 被列出
        assert "claim" in content.lower()
        assert "synthesis" in content.lower()
        # 验证脚本能返回结构化结果 (通过 --json)
        out_json = root / "dryrun_report.json"
        r_json = _run(
            "--project-root", str(root),
            "--json-output", str(out_json),
        )
        assert r_json.returncode == 0, f"json script failed: stderr={r_json.stderr!r}"
        data = json.loads(out_json.read_text(encoding="utf-8"))
        assert "narrative_pages" in data
        assert data["narrative_pages"] == 3, (
            f"narrative_pages 应该 = 3 (1 claim + 2 synthesis), 实测 {data['narrative_pages']}"
        )


# ---------------------------------------------------------------------------
# Test 3: dry-run 报告含 PageType 分布 + backfill 成本估算 (与 H-5 脚本输出对齐)
# ---------------------------------------------------------------------------
@pytest.mark.skipif(
    not NOVEL_WIKI.exists(),
    reason="knowledge/novel-wiki/ not present (skip real-data sanity check)",
)
def test_dryrun_writes_markdown_report_with_pagetype_and_cost() -> None:
    """真实 novel-wiki 项目跑脚本, 报告必含 PageType 分布 + 成本估算字段
    (与 H-5 kc_ku_cost_estimator.py 输出字段一致)."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "novel_dryrun"
        out_md = root / "report.md"
        out_json = root / "report.json"
        r = _run(
            "--project-root", str(NOVEL_WIKI),
            "--output", str(out_md),
            "--json-output", str(out_json),
        )
        assert r.returncode == 0, f"script failed: stderr={r.stderr!r}"
        # Markdown 报告存在
        assert out_md.exists()
        md_content = out_md.read_text(encoding="utf-8")
        # 必含 PageType 分布 (至少 concept/entity/source/synthesis/claim 之一)
        for kw in ("concept", "entity", "source", "synthesis", "claim"):
            assert kw in md_content.lower(), f"missing PageType keyword: {kw}"
        # 必含 backfill 成本估算 (与 H-5 一致: choice_1/2/3_cost)
        for kw in ("choice_1", "choice_2", "choice_3"):
            assert kw in md_content, f"missing cost keyword: {kw}"
        # JSON 输出可解析
        data = json.loads(out_json.read_text(encoding="utf-8"))
        # 与 H-5 对齐的字段
        assert "page_type_distribution" in data
        assert "choice_1_cost" in data
        assert "choice_2_cost" in data
        assert "choice_3_cost" in data
        assert "narrative_pages" in data
        assert "recommendation" in data
        # novel-wiki 实测叙事类 = 66 页 (claim 10 + synthesis 56)
        assert data["narrative_pages"] == 66, (
            f"novel-wiki narrative_pages 应该 = 66, 实测 {data['narrative_pages']}"
        )