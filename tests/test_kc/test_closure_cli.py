"""Tests for 30-day transition CLI (B-3 commit 3 — H-2 决策 + spec §11.3).

路线 v2.2 §B-3 — 30 天过渡期 CLI (kc closure enable / kc closure migrate-legacy).

TDD coverage (4 tests):
1. ``cmd_enable_closure(args_without_confirm)`` → 返回 exit code 1
2. ``cmd_enable_closure(args_with_confirm)`` → 返回 exit code 0 + 写 transition log
3. ``cmd_migrate_legacy(args_without_confirm)`` → 返回 exit code 1
4. ``cmd_migrate_legacy(args_with_confirm)`` → 返回 exit code 0

集成:
- H-2 决策: 30 天过渡期 warn 日志 + 二次确认 + legacy 兜底
- kc closure enable --confirm: 二次确认 + 写 .index/closure_transition.log
- kc closure migrate-legacy --confirm: 二次确认 + 简化 (仅打印统计)
- 完整 WikiPage frontmatter 修改留 B-3.x 后续 (backfill verified_at)

Ref: docs/architecture/B-2_11_Gate_design.md §4 + H-2 决策 + spec §11.3.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest


# ─── 测试夹具 ──────────────────────────────────────────────────────────────


def _make_args(
    project_root: Path,
    confirm: bool = False,
    operator: str = "admin",
) -> argparse.Namespace:
    """构造 argparse.Namespace — 模拟 CLI 调用."""
    return argparse.Namespace(
        project_root=project_root,
        confirm=confirm,
        operator=operator,
    )


@pytest.fixture
def tmp_project_root(tmp_path) -> Path:
    """临时项目根目录 + wiki/ 子目录 (migrate-legacy 需要)."""
    project_root = tmp_path / "project"
    project_root.mkdir()
    wiki_dir = project_root / "wiki"
    wiki_dir.mkdir()
    return project_root


# ─── TDD 测试 ──────────────────────────────────────────────────────────────


class TestClosureCLI:
    """spec H-2 + §11.3 30 天过渡期 CLI."""

    def test_enable_closure_without_confirm_rejects(self, tmp_project_root, capsys):
        """cmd_enable_closure(args_without_confirm) → 返回 exit code 1.

        缺 --confirm 视为需要二次确认 → 返回 1 (不写入 transition log).
        """
        from src.cli_ext.closure_cmd import cmd_enable_closure

        args = _make_args(tmp_project_root, confirm=False)

        exit_code = cmd_enable_closure(args)

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "--confirm" in captured.out

        # 验证未写 transition log
        transition_log = tmp_project_root / ".index" / "closure_transition.log"
        assert not transition_log.exists()

    def test_enable_closure_with_confirm_writes_log(self, tmp_project_root, capsys):
        """cmd_enable_closure(args_with_confirm) → 返回 exit code 0 + 写 transition log.

        --confirm 后写 .index/closure_transition.log (append-only).
        """
        from src.cli_ext.closure_cmd import cmd_enable_closure

        args = _make_args(tmp_project_root, confirm=True, operator="admin")

        exit_code = cmd_enable_closure(args)

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "✅" in captured.out or "30" in captured.out

        # 验证写 transition log
        transition_log = tmp_project_root / ".index" / "closure_transition.log"
        assert transition_log.exists()

        # 验证日志内容
        lines = transition_log.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) >= 1
        entry = json.loads(lines[-1])
        assert entry["action"] == "enable_closure"
        assert entry["transition_days"] == 30
        assert entry["operator"] == "admin"

    def test_migrate_legacy_without_confirm_rejects(self, tmp_project_root, capsys):
        """cmd_migrate_legacy(args_without_confirm) → 返回 exit code 1.

        缺 --confirm 视为需要二次确认 → 返回 1.
        """
        from src.cli_ext.closure_cmd import cmd_migrate_legacy

        args = _make_args(tmp_project_root, confirm=False)

        exit_code = cmd_migrate_legacy(args)

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "--confirm" in captured.out

    def test_migrate_legacy_with_confirm_returns_zero(self, tmp_project_root, capsys):
        """cmd_migrate_legacy(args_with_confirm) → 返回 exit code 0.

        --confirm 后简化: 仅打印统计, 实际 WikiPage frontmatter 修改留 B-3.x 后续.
        """
        from src.cli_ext.closure_cmd import cmd_migrate_legacy

        args = _make_args(tmp_project_root, confirm=True)

        exit_code = cmd_migrate_legacy(args)

        assert exit_code == 0
        captured = capsys.readouterr()
        # 简化: 打印统计 + 提示实际 backfill 留后续
        assert "找到" in captured.out or "wiki" in captured.out.lower()
