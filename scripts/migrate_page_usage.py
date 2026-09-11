"""Grant the single actionable tag only to pages with human approval.

The default is a read-only preview. ``--apply`` updates derived wiki pages
through the existing atomic writer; raw sources are never opened for write.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.lib.atomic_ctx import AtomicContext  # noqa: E402
from src.lib.write_hooks import flush_pending_writes  # noqa: E402
from src.wiki.core.paths import WikiPaths  # noqa: E402
from src.wiki.features.review import has_approved_usage_review  # noqa: E402
from src.wiki.features.tag_namespace import ACTIONABLE_TAG  # noqa: E402
from src.wiki.storage.page_writer import read_page, write_page  # noqa: E402


def _candidate_pages(paths: WikiPaths) -> list[tuple[Path, object]]:
    pages: list[tuple[Path, object]] = []
    for path in sorted(paths.wiki.rglob("*.md")):
        if path.name in {"index.md", "log.md"}:
            continue
        page = read_page(path)
        if has_approved_usage_review(paths, page.id) and ACTIONABLE_TAG not in page.tags:
            pages.append((path, page))
    return pages


def migrate_page_usage(project_root: Path, *, apply: bool = False) -> dict[str, list[str]]:
    """Preview or apply approved actionable tags for one project."""
    paths = WikiPaths(Path(project_root).resolve())
    candidates = _candidate_pages(paths)
    planned = [page.id for _, page in candidates]
    if not apply:
        return {"planned": planned, "applied": []}

    with AtomicContext(flush_callback=flush_pending_writes):
        for _, page in candidates:
            page.tags = [*page.tags, ACTIONABLE_TAG]
            write_page(paths, page)
    return {"planned": planned, "applied": planned}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", type=Path, nargs="?", default=Path("knowledge/novel-wiki"))
    parser.add_argument("--apply", action="store_true", help="apply approved tags")
    args = parser.parse_args(argv)
    result = migrate_page_usage(args.project_root, apply=args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
