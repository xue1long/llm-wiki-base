"""rollback_batch.py — 批回滚 = git checkout 快照 + 向量重建 双动作（plan guidance #6）。

Phase 4 P1 P0 加固：门禁数据 git 跟踪（.gitignore 白名单例外），回滚脚本化。
回滚是**双动作**：
1. ``git checkout <git_snapshot>`` —— 把 wiki 页面恢复到批前快照（批前
   ``batch_executor`` 会把 HEAD 记入 ``batch_build_state.json`` 的
   ``batch_<n>.git_snapshot``）；
2. 向量重建 —— ``rebuild_vector_schema``（显式 drop + 重建，维度决策已在
   T4.3 完成；lancedb 不入 git，回滚后必须重建才能与页面一致）。

安全语义：无快照 / 非 git 仓库 → 明确报错（exit 1），不做部分回滚
（绝不"只 checkout 页面不重建向量"或反之的裸状态）。

用法::

    PYTHONPATH=. python scripts/rollback_batch.py <project_root> [--batch 0] [--yes]

    --yes 跳过二次确认（脚本默认打印计划并等待 y/N，非交互环境用 --yes）。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.services.batch_state import load_batch_state  # noqa: E402
from src.wiki.core.paths import WikiPaths  # noqa: E402


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )


def rollback_batch(root: Path, batch_key: str = "batch_0", assume_yes: bool = False) -> int:
    """执行批回滚。返回 exit code（0 成功 / 1 缺前置条件或取消）。"""
    paths = WikiPaths(root)

    # 1. 读快照
    state = load_batch_state(paths)
    entry = state.get(batch_key, {})
    snapshot = entry.get("git_snapshot") if isinstance(entry, dict) else None
    if not snapshot:
        print(f"ERROR: {batch_key} has no git_snapshot — nothing to roll back to",
              file=sys.stderr)
        return 1

    # 2. 校验 git 仓库
    check = _git(root, "rev-parse", "--is-inside-work-tree")
    if check.returncode != 0:
        print(f"ERROR: {root} is not a git repository", file=sys.stderr)
        return 1

    # 3. 打印计划 + 二次确认
    print(f"Rollback plan for {batch_key} @ {snapshot[:12]}:")
    print(f"  1. git checkout {snapshot[:12]} -- wiki/")
    print("  2. rebuild LanceDB chunks table (explicit drop + recreate)")
    if not assume_yes:
        try:
            ans = input("Proceed? [y/N] ").strip().lower()
        except EOFError:
            ans = "n"
        if ans not in ("y", "yes"):
            print("cancelled")
            return 1

    # 4. git checkout wiki/（回滚已跟踪文件）+ git clean -f wiki/（清掉未跟踪
    #    的新页，如批内新生成但未提交的 concept/entity 页）——只动 wiki/，
    #    不碰 raw/ 与 .index 之外的配置。
    co = _git(root, "checkout", snapshot, "--", "wiki")
    if co.returncode != 0:
        print(f"ERROR: git checkout failed: {co.stderr}", file=sys.stderr)
        return 1
    cl = _git(root, "clean", "-f", "--", "wiki")
    if cl.returncode != 0:
        print(f"ERROR: git clean failed: {cl.stderr}", file=sys.stderr)
        return 1
    print(f"  [ok] wiki/ restored to {snapshot[:12]} "
          f"(tracked checkout + untracked clean)")

    # 5. 向量重建（显式，T4.3 决策路径）
    from src.vector.store import rebuild_vector_schema
    old_dim = rebuild_vector_schema(paths)
    print(f"  [ok] LanceDB chunks rebuilt (previous dim={old_dim})")

    print("ROLLBACK DONE — 页面已回滚、向量已重建")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="批回滚 = git checkout + 向量重建")
    ap.add_argument("root", type=Path, help="project root")
    ap.add_argument("--batch", default="batch_0", help="batch key (default batch_0)")
    ap.add_argument("--yes", action="store_true", help="skip confirmation")
    args = ap.parse_args(argv)
    return rollback_batch(args.root, batch_key=args.batch, assume_yes=args.yes)


if __name__ == "__main__":
    sys.exit(main())
