"""cleanup_invalid_tags.py — 清理 wiki 页面中的非法/legacy tag（M8 旧英文 tag 治理）。

统一走 ``tag_namespace.normalize_tags``（计划 2026-08-18 Task 4）：
- legacy 前缀（``genre/``、``func/`` 等）可确定映射的自动映射
  （如 ``func/教程`` → ``功能/教程``）
- 无法安全映射 / 值域非法的 tag 删除并记录 warning
- 按当前兼容政策（策略 1）自动补 mandatory（``素材/ugc`` / ``可信度/ugc``）

dry-run 输出 mapping / removal / mandatory 清单；``--apply`` 才实际写入。

用法::

    # 指定页面（逗号分隔）dry-run
    python scripts/cleanup_invalid_tags.py --root knowledge/novel-wiki \
        --page-ids 势力架构,技能体系设定

    # 全库 dry-run
    python scripts/cleanup_invalid_tags.py --root knowledge/novel-wiki --all

    # 实际写入
    python scripts/cleanup_invalid_tags.py --root knowledge/novel-wiki \
        --page-ids 势力架构,技能体系设定,装备设定,身世设定 --apply
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.wiki.features.tag_namespace import normalize_tags  # noqa: E402
from src.wiki.storage.page_writer import read_page, write_page  # noqa: E402
from src.wiki.core.paths import WikiPaths  # noqa: E402

WIKI_SUBDIRS = ("wiki_sources", "wiki_entities", "wiki_concepts", "wiki_synthesis")


def _iter_pages(paths: WikiPaths):
    for attr in WIKI_SUBDIRS:
        d = getattr(paths, attr, None)
        if d is None or not d.exists():
            continue
        for f in sorted(d.glob("*.md")):
            try:
                yield f, read_page(f)
            except Exception:
                continue


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--page-ids", default="", help="comma-separated page ids")
    ap.add_argument("--all", action="store_true", help="scan all wiki pages")
    ap.add_argument("--apply", action="store_true", help="write changes")
    args = ap.parse_args()

    root = Path(args.root)
    paths = WikiPaths(root)
    page_ids = {s.strip() for s in args.page_ids.split(",") if s.strip()}
    if not args.all and not page_ids:
        print("provide --page-ids or --all", file=sys.stderr)
        return 2

    total_files = 0
    total_removed = 0
    for path, page in _iter_pages(paths):
        if not args.all and page.id not in page_ids:
            continue
        if not page.tags:
            continue
        result = normalize_tags(list(page.tags or []), source_path=str(path))
        if not (result.mapped or result.removed or result.mandatory_added):
            continue
        total_files += 1
        total_removed += len(result.removed)
        for _orig, _new in result.mapped.items():
            print(f"{page.id}: map {_orig} -> {_new}")
        for _rem in result.removed:
            print(f"{page.id}: remove {_rem}")
        for _add in result.mandatory_added:
            print(f"{page.id}: add mandatory {_add}")
        if args.apply:
            page.tags = result.tags
            write_page(paths, page)

    print(f"[cleanup] scanned {total_files} file(s) with tag changes, "
          f"removed {total_removed} tag(s)")
    if args.apply:
        print("[cleanup] WROTE changes")
    else:
        print("[cleanup] dry-run — pass --apply to write")
    return 0


if __name__ == "__main__":
    sys.exit(main())
