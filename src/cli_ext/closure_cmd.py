"""spec §11.3 + H-2 30 天过渡期 CLI (B-3 commit 3).

Public API:
    cmd_enable_closure(args)    — kc closure enable --confirm
    cmd_migrate_legacy(args)    — kc closure migrate-legacy --confirm
    register(subparsers)        — 注册 closure 子命令到主 CLI

集成:
- H-2 决策: 30 天过渡期 warn 日志 + 二次确认 + legacy 兜底
- kc closure enable --confirm:
  * 二次确认 (缺 --confirm 返回 1)
  * 写 .index/closure_transition.log (append-only)
- kc closure migrate-legacy --confirm:
  * 二次确认
  * 简化: 仅打印统计, 实际 WikiPage frontmatter 修改留 B-3.x 后续
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def cmd_enable_closure(args: argparse.Namespace) -> int:
    """kc closure enable --confirm: 启动 30 天过渡期.

    spec H-2 决策: warn 日志 + 二次确认 + legacy 兜底.

    Args:
        args: argparse.Namespace (project_root, confirm, operator)

    Returns:
        exit code (0 = 成功, 1 = 缺 --confirm, 2 = 其他错误)
    """
    if not args.confirm:
        print("ERROR: 需 --confirm 参数二次确认", file=sys.stdout)
        print(
            "提示: 30 天过渡期会启用 DefaultClosure 校验, "
            "现有页面 verified_at=0 可能被过滤",
            file=sys.stdout,
        )
        return 1

    project_root = Path(args.project_root)
    transition_log = project_root / ".index" / "closure_transition.log"
    transition_log.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        "timestamp": int(time.time() * 1000),
        "action": "enable_closure",
        "transition_days": 30,
        "operator": getattr(args, "operator", "unknown"),
    }

    with transition_log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(
        f"✅ 30 天过渡期已启用 (timestamp: {entry['timestamp']})",
        file=sys.stdout,
    )
    print(f"   transition log: {transition_log}", file=sys.stdout)
    print(
        "   30 天后请执行: kc closure migrate-legacy",
        file=sys.stdout,
    )
    return 0


def cmd_migrate_legacy(args: argparse.Namespace) -> int:
    """kc closure migrate-legacy --confirm: 30 天后机械化 backfill verified_at.

    spec H-2 决策: legacy 兜底 (verified_at = ingestion_unix_ms).

    Args:
        args: argparse.Namespace (project_root, confirm)

    Returns:
        exit code (0 = 成功, 1 = 缺 --confirm, 2 = wiki dir 不存在)
    """
    if not args.confirm:
        print("ERROR: 需 --confirm 参数二次确认", file=sys.stdout)
        print(
            "提示: 此操作会修改所有现有 WikiPage 的 verified_at 字段",
            file=sys.stdout,
        )
        return 1

    project_root = Path(args.project_root)
    wiki_dir = project_root / "wiki"

    if not wiki_dir.exists():
        print(f"ERROR: {wiki_dir} 不存在", file=sys.stdout)
        return 1

    # 简化: 仅打印统计, 不实际修改
    md_files = list(wiki_dir.rglob("*.md"))
    print(f"找到 {len(md_files)} 个 wiki markdown 文件", file=sys.stdout)
    print(
        "⚠️ 实际 backfill 需实现 WikiPage frontmatter 修改 (留 B-3.x 后续)",
        file=sys.stdout,
    )
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    """注册 closure 子命令到主 CLI.

    Args:
        subparsers: argparse subparsers (来自主 parser)
    """
    parser = subparsers.add_parser(
        "closure",
        help="B-3 默认发布闭包 + 30 天过渡期管理",
    )
    sub = parser.add_subparsers(dest="closure_action", required=True)

    # kc closure enable --confirm
    p_enable = sub.add_parser(
        "enable", help="启用 30 天过渡期 (需 --confirm)"
    )
    p_enable.add_argument(
        "--project-root", type=Path, required=True,
    )
    p_enable.add_argument(
        "--confirm", action="store_true", help="二次确认",
    )
    p_enable.add_argument(
        "--operator", type=str, default="admin",
    )
    p_enable.set_defaults(func=cmd_enable_closure)

    # kc closure migrate-legacy --confirm
    p_migrate = sub.add_parser(
        "migrate-legacy", help="30 天后 backfill verified_at (需 --confirm)",
    )
    p_migrate.add_argument(
        "--project-root", type=Path, required=True,
    )
    p_migrate.add_argument(
        "--confirm", action="store_true", help="二次确认",
    )
    p_migrate.set_defaults(func=cmd_migrate_legacy)
