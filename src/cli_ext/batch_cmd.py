"""batch_cmd.py — `ruflo batch` CLI subcommands (P1-A 3d).

Wraps the ``scripts/batch_*.py`` legacy CLIs as ``ruflo batch`` subcommands,
so each script can be invoked either via ``python scripts/<name>.py`` or
``ruflo batch <name>`` (compatible transition period).

Subcommands:
- ``run`` — 执行一批（进程内，wrap batch_executor.py 的 main()）
- ``plan`` — 生成批量摄入计划（进程内，wrap plan_reingest_batches.py）
- ``gate-check / gate-v3 / diagnose-gate / accept / generate / commit /
  build / ingest / rollback / pilot / phase3-accept / phase4 /
  phase5-accept / plan-first / plan-backlog`` — 子进程转发原脚本，透传
  args 与退出码（零行为风险，原脚本直跑入口保留）。
"""
from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from pathlib import Path

from src.orchestrator.batch_runner import (
    DEFAULT_CONCURRENCY,
    DEFAULT_MANIFEST,
    DefaultBatchRunner,
    run_batch,
)

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"

# (subcommand, script name, help)
_SCRIPT_SUBCOMMANDS = [
    ("gate-check", "batch_gate_check", "批级质量门禁（P1-P7 + P4b）"),
    ("gate-v3", "batch_gate_v3", "post-ingest 批级门禁（M1/M2/M4/M6/M7）"),
    ("diagnose-gate", "diagnose_batch_gate", "复现某批整批复核并打印完整 issues"),
    ("accept", "accept_batch", "整批复核通过后标记 committed"),
    ("generate", "batch_generate", "并行生成批次（零磁盘写，产物缓存）"),
    ("commit", "batch_commit", "串行提交批次（消费 generate 缓存）"),
    ("build", "batch_build", "批量构建知识库（ingest + archive 两段式）"),
    ("ingest", "batch_ingest", "批量摄取文档（HTTP API）"),
    ("rollback", "rollback_batch", "批回滚 = git checkout + 向量重建"),
    ("pilot", "pilot_ingest", "Phase 4.2 pilot 随机重摄取"),
    ("phase3-accept", "phase3_accept", "Phase 3 首批验收"),
    ("phase4", "phase4_batch", "Phase 4 批执行（generate→reconcile→gate→commit）"),
    ("phase5-accept", "phase5_accept", "Phase 5 终验报告"),
    ("plan-first", "plan_gap_first_batch", "B12 缺口优先首批清单"),
    ("plan-backlog", "build_reingest_backlog", "全量重摄入 backlog 清单"),
]


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

    # Legacy script wrappers (zero-touch subprocess forwarding)
    for name, script, desc in _SCRIPT_SUBCOMMANDS:
        sp = p_batch_sub.add_parser(name, help=desc)
        sp.add_argument("args", nargs=argparse.REMAINDER,
                        help=f"透传给 scripts/{script}.py 的参数")
        sp.set_defaults(func=_make_script_runner(script))


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
