"""accept_batch.py — 整批复核通过后，将批次状态置为 committed。

当 batch 状态为 ``gate_recheck_failed`` 且人工已修复页面（如清理非法 tag）
时，运行本脚本：
  1. 从磁盘读取该批 page_ids 页面，跑完整 pre-commit gate
  2. 通过 → 更新 batch_build_state.json：status=committed、清空 gate_issues
  3. 不通过 → 打印全部 issues，状态不变

用法::

    PYTHONPATH=. python scripts/accept_batch.py --root knowledge/novel-wiki --batch 2
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.services.batch_state import load_batch_state, update_batch_state  # noqa: E402
from src.wiki.core.paths import WikiPaths  # noqa: E402
from src.wiki.storage.page_writer import read_page  # noqa: E402
from src.wiki.features.batch_gate import run_precommit_gate  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--batch", type=int, required=True)
    args = ap.parse_args()

    root = Path(args.root)
    paths = WikiPaths(root)
    state = load_batch_state(paths)
    batch_key = f"batch_{args.batch}"
    batch = state.get(batch_key, {})
    if not batch:
        print(f"batch {args.batch} not found in batch_build_state.json")
        return 1

    page_ids = batch.get("page_ids", [])
    files = batch.get("completed_files", [])
    print(f"batch {args.batch}: status={batch.get('status')} "
          f"page_ids={len(page_ids)} completed_files={len(files)}")

    pages = []
    id_set = set(page_ids)
    for sub in (paths.wiki_sources, paths.wiki_entities,
                paths.wiki_concepts, paths.wiki_synthesis):
        if not sub.exists():
            continue
        for f in sub.glob("*.md"):
            try:
                pg = read_page(f)
            except Exception:
                continue
            if pg.id in id_set:
                pages.append(pg)
    missing_ids = sorted(id_set - {p.id for p in pages})
    if missing_ids:
        print(f"MISSING {len(missing_ids)} page id(s): {missing_ids[:20]}")
        return 1

    passed, issues = run_precommit_gate(pages, [], {}, paths, allow_overwrite=True)
    if not passed:
        print(f"GATE FAIL ({len(issues)} issue(s)) — not accepting")
        for iss in issues:
            print(f"  {iss}")
        return 2

    def _mutate(st: dict) -> dict:
        entry = st.setdefault(batch_key, {})
        entry["status"] = "committed"
        entry["ts"] = __import__("time").strftime("%Y-%m-%dT%H:%M:%S")
        entry.pop("gate_issues", None)
        return st

    update_batch_state(paths, _mutate)
    print(f"GATE PASS — batch {args.batch} marked committed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
