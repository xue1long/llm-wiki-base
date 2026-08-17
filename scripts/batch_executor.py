"""batch_executor.py — Phase 4 直跑批执行器 CLI 壳（P1-A 3b 拆引擎后）。

引擎逻辑（状态机、三阶段原子流程、崩溃续跑、预算暂停、测试钩子）已迁至
``src/orchestrator/batch_runner.py``；本文件仅保留 CLI 壳（argparse +
``main()``）和向后兼容的 re-export。

用法::

    PYTHONPATH=. python scripts/batch_executor.py --root <project_root> \\
        --manifest .index/reingest_plan.json --batch 0 [--resume]
    PYTHONPATH=. python scripts/batch_executor.py --project <id> --batch 0 [--budget-usd 0.2]

退出码：
  0  批完成（committed）
  1  manifest/参数错误 或 无可处理文件
  2  门禁失败（零写入，pre-commit 阶段拦截）
  3  整批门禁复核失败（页面已提交，须 rollback_batch）或 预算超限暂停
  137 kill -9 注入
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ── Re-export engine symbols for backward compatibility ──────────────────
# batch_commit.py, batch_generate.py, test_batch_executor.py 等仍通过
# "from scripts.batch_executor import ..." 引用引擎函数。
from src.orchestrator.batch_runner import (  # noqa: E402
    _auto_tag_ugc,
    _commit_raw,
    _crash_at,
    _estimate_batch_cost,
    _fake_generate,
    _generate_raw,
    _git_snapshot,
    _is_fake_mode,
    _is_immutable_source,
    _rerun_gate_batch,
    _resolve_paths,
    _resolve_provider,
    _set_batch_status,
    _update_fail_streak,
    _upsert_batch_vectors,
    run_batch,
)

# gate 函数也经 batch_runner 透传（真源在 src/wiki/features/batch_gate.py）
from src.orchestrator.batch_runner import (  # noqa: E402, F811
    run_precommit_gate,
)

# 常量
from src.orchestrator.batch_runner import (  # noqa: E402
    DEFAULT_CONCURRENCY,
    DEFAULT_MANIFEST,
    MAX_FAIL_STREAK,
    CRASH_STAGES,
)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    ap = argparse.ArgumentParser(description="Phase 4 直跑批执行器")
    ap.add_argument("--manifest", default=DEFAULT_MANIFEST)
    ap.add_argument("--batch", type=int, default=0)
    ap.add_argument("--project", default=None, help="project id (registry)")
    ap.add_argument("--root", default=None, help="project root (直跑/测试)")
    ap.add_argument("--resume", action="store_true",
                    help="续跑：跳过 done、重跑 pending_deletion/failed")
    ap.add_argument("--budget-usd", type=float, default=None,
                    help="累计费用预算，超限自动暂停")
    ap.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    ap.add_argument("--allow-overwrite", action="store_true")
    ap.add_argument("--no-git-snapshot", action="store_true")
    args = ap.parse_args(argv)

    if not args.project and not args.root:
        print("ERROR: provide --project <id> or --root <path>", flush=True)
        return 1
    if args.budget_usd is not None and args.budget_usd <= 0:
        print("ERROR: --budget-usd must be > 0", flush=True)
        return 1
    if args.batch < 0:
        print("ERROR: --batch must be >= 0", flush=True)
        return 1
    if args.concurrency < 1:
        print("ERROR: --concurrency must be >= 1", flush=True)
        return 1

    return asyncio.run(run_batch(args))


if __name__ == "__main__":
    sys.exit(main())