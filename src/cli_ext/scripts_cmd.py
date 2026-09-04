"""scripts_cmd.py — `ruflo migrate` / `audit` / `util` CLI subcommands.

Wraps the remaining legacy ``scripts/*.py`` CLIs as ``ruflo <group> <name>``
subcommands via subprocess forwarding (zero-touch, original scripts still
runnable directly as ``python scripts/<name>.py``).

Groups:
- ``migrate`` — 5 个迁移脚本（migrate_*）
- ``audit`` — 4 个审计/质检脚本（audit_* / quality_check_wiki）
- ``util`` — 其余运维工具箱（aggregate_synthesis / cleanup_* / fix_* / ndg_* / ...）
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"


def _run_script(script: str, argv: list[str]) -> None:
    """Run ``python scripts/<script>.py <argv...>`` and propagate the exit code."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_SCRIPTS_DIR.parent)
    proc = subprocess.run(
        [sys.executable, str(_SCRIPTS_DIR / f"{script}.py"), *argv],
        env=env,
    )
    sys.exit(proc.returncode)


def _make_script_runner(script: str):
    def _cmd(args) -> None:
        _run_script(script, list(args.args))
    return _cmd


def _add_script_group(
    subparsers,
    group_name: str,
    group_help: str,
    scripts: list[tuple[str, str, str]],
    subparsers_dest: str | None = None,
):
    """Register a group of subcommands that forward to legacy scripts."""
    p_group = subparsers.add_parser(group_name, help=group_help)
    p_group_sub = p_group.add_subparsers(
        dest=subparsers_dest or f"{group_name}_command", required=True
    )
    for name, script, desc in scripts:
        sp = p_group_sub.add_parser(name, help=desc)
        sp.add_argument("args", nargs=argparse.REMAINDER,
                        help=f"透传给 scripts/{script}.py 的参数")
        sp.set_defaults(func=_make_script_runner(script))


def add_scripts_subcommands(subparsers) -> None:
    """Register ``ruflo migrate`` / ``audit`` / ``util`` subcommand groups."""

    _add_script_group(
        subparsers, "migrate", "数据迁移工具（5 个 migrate_* 脚本）",
        [
            ("legacy-tags", "migrate_legacy_tags", "迁移旧版 tag 命名空间"),
            ("pinyin-to-cjk", "migrate_pinyin_to_cjk_aliases", "拼音别名 → CJK 别名迁移"),
            ("slug-aliases", "migrate_slug_aliases", "slug 别名迁移"),
            ("timestamps", "migrate_timestamps_to_date", "时间戳 → 日期迁移"),
            ("vector-paths", "migrate_vector_paths", "向量存储路径迁移"),
        ],
    )

    _add_script_group(
        subparsers, "audit", "审计与质量检查（4 个脚本）",
        [
            ("blindspots", "audit_blindspots", "盲区审计"),
            ("placeholder-classify", "audit_placeholder_classify", "占位符分类审计"),
            ("wiki-baseline", "audit_wiki_baseline", "wiki 基线审计"),
            ("quality-check", "quality_check_wiki", "wiki 质量检查"),
        ],
    )

    _add_script_group(
        subparsers, "util", "运维工具箱（其余遗留脚本）",
        [
            ("aggregate-synthesis", "aggregate_synthesis", "多源 synthesis 聚合"),
            ("cleanup-stubs", "cleanup_stub_pages", "清理 stub/placeholder 页面"),
            ("cleanup-tags", "cleanup_invalid_tags", "清理无效 tag"),
            ("fix-mojibake", "fix_mojibake_sources", "修复乱码源文件"),
            ("ndg-calibrate", "ndg_calibrate", "NDG RAW-PASTE 阈值校准"),
            ("normalize-sources", "normalize_sources", "源文件规范化"),
            ("rebuild-index", "rebuild_index", "重建 wiki index.md"),
            ("stress-test", "stress_test_ingest", "摄取压力测试"),
            ("sync-wiki-spec", "sync_wiki_spec", "同步 wiki-spec.md → 提示词"),
            ("setup-git-hooks", "setup_git_hooks", "安装 git 钩子"),
            ("ingest-d", "ingest_novel_wiki_d", "批量摄取 D 系列文档"),
            ("ingest-manual", "ingest_novel_wiki_manual", "手动摄取 novel wiki"),
        ],
    )
