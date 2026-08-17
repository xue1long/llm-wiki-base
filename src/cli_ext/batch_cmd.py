"""batch_cmd.py — `ruflo batch` CLI subcommands (P1-A 3d).

Wraps ``scripts/batch_executor.py`` (引擎在 ``src/orchestrator/batch_runner.py``)
为 ``ruflo batch run`` 子命令，使原有脚本可通过 `python scripts/batch_*.py` 或
`ruflo batch run` 两种方式调用（兼容过渡期）。

子命令：
- ``run`` — 执行一批（wrap batch_executor.py 的 main()）
- ``plan`` — 生成批量摄入计划（wrap plan_reingest_batches.py）
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from src.orchestrator.batch_runner import (
    DEFAULT_CONCURRENCY,
    DEFAULT_MANIFEST,
    DefaultBatchRunner,
    run_batch,
)


def _inject_runner(args) -> None:
    """将 DefaultBatchRunner 注入 args，使 run_batch 触发生命周期钩子。"""
    args._batch_runner = DefaultBatchRunner(args)


def add_batch_subcommands(subparsers) -> None:
    """Register ``ruflo batch`` subcommands on the given subparsers object."""
    p_batch = subparsers.add_parser("batch", help="批量摄入执行（BatchRunner 框架）")
    p_batch_sub = p_batch.add_subparsers(dest="batch_command", required=True)

    # ruflo batch run
    p_run = p_batch_sub.add_parser("run", help="执行一批摄入（原 batch_executor.py）")
    p_run.add_argument("--manifest", default=DEFAULT_MANIFEST)
    p_run.add_argument("--batch", type=int, default=0)
    p_run.add_argument("--project", default=None, help="project id (registry)")
    p_run.add_argument("--root", default=None, help="project root (直跑/测试)")
    p_run.add_argument("--resume", action="store_true",
                       help="续跑：跳过 done、重跑 pending_deletion/failed")
    p_run.add_argument("--budget-usd", type=float, default=None,
                       help="累计费用预算，超限自动暂停")
    p_run.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    p_run.add_argument("--allow-overwrite", action="store_true")
    p_run.add_argument("--no-git-snapshot", action="store_true")
    p_run.set_defaults(func=cmd_batch_run)

    # ruflo batch plan
    p_plan = p_batch_sub.add_parser("plan", help="生成批量摄入计划")
    p_plan.add_argument("--root", required=True, help="project root")
    p_plan.add_argument("--out", default=None,
                        help="输出路径（默认 .index/reingest_plan.json）")
    p_plan.set_defaults(func=cmd_batch_plan)


def cmd_batch_run(args) -> None:
    """ruflo batch run — 执行一批摄入。"""
    _inject_runner(args)
    exit_code = asyncio.run(run_batch(args))
    sys.exit(exit_code)


def cmd_batch_plan(args) -> None:
    """ruflo batch plan — 生成批量摄入计划。"""
    from scripts.plan_reingest_batches import main as plan_main
    sys_argv = ["plan_reingest_batches.py", "--root", args.root]
    if args.out:
        sys_argv.extend(["--out", args.out])
    sys.exit(plan_main(sys_argv[1:]))