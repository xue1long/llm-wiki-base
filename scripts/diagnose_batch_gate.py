"""diagnose_batch_gate.py — 复现某批整批复核并打印完整 issues（排查用）。

用法::

    PYTHONPATH=. python scripts/diagnose_batch_gate.py --root knowledge/novel-wiki --batch 2

输出：
- 该批 page_ids 数量
- 磁盘实际读到的页面数量
- 整批复核 run_precommit_gate 的完整 issues（不截断 10 条）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.services.batch_state import load_batch_state  # noqa: E402
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

    # 从磁盘读取本批实际页面（与 _rerun_gate_batch 同逻辑）
    pages = []
    missing_ids = []
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
    found = {p.id for p in pages}
    missing_ids = sorted(id_set - found)
    print(f"loaded {len(pages)} page(s), missing {len(missing_ids)} page id(s)")
    if missing_ids:
        print("MISSING IDs (disk not found):")
        for pid in missing_ids[:50]:
            print(f"  {pid}")

    if not pages:
        print("no pages loaded — nothing to gate")
        return 1

    passed, issues = run_precommit_gate(
        pages, [], {}, paths, allow_overwrite=True)
    print(f"GATE {'PASS' if passed else 'FAIL'} ({len(issues)} issue(s))")
    for iss in issues:
        print(f"  {iss}")
    return 0 if passed else 2


if __name__ == "__main__":
    sys.exit(main())
