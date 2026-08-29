"""Migrate an existing ruflo wiki to the GBrain-compatible Markdown shape.

Usage::

    python scripts/migrate_wiki_to_gbrain.py --root knowledge/novel-wiki
    python scripts/migrate_wiki_to_gbrain.py --root knowledge/novel-wiki --apply

The default is a report-only dry run. Applied pages are written through the
normal page writer, which keeps a version snapshot before overwriting.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from src.wiki.core.paths import WikiPaths
from src.wiki.features.gbrain_compat import (
    build_target_slugs,
    gbrain_slug_for_path,
    materialize_relations,
    rewrite_wikilinks,
)
from src.wiki.schema_registry import SchemaRegistry
from src.wiki.storage.page_writer import page_path_for, read_page, write_page


def _page_files(paths: WikiPaths) -> list[Path]:
    registry = SchemaRegistry.from_project(paths.root)
    return [
        path
        for directory in registry.iter_page_dirs(paths)
        if directory.exists()
        for path in directory.glob("*.md")
        if path.name not in {"index.md", "log.md"}
    ]


def migrate(paths: WikiPaths, *, apply: bool = False) -> dict[str, int]:
    files = _page_files(paths)
    pages: list[tuple[Path, object]] = []
    errors = 0
    for path in files:
        try:
            pages.append((path, read_page(path)))
        except Exception as exc:
            errors += 1
            print(f"ERROR {path}: {exc}")

    targets = build_target_slugs(
        paths,
        [(page.id, path) for path, page in pages],
    )
    changed = 0
    for path, page in pages:
        expected_slug = gbrain_slug_for_path(paths, path)
        expected_body = materialize_relations(
            rewrite_wikilinks(page.body, targets), page.relations, targets,
        )
        has_slug = bool(
            re.search(r"(?m)^slug:\s*\S+", path.read_text(encoding="utf-8"))
        )
        if not has_slug or page.body != expected_body:
            changed += 1
        if apply:
            page.body = expected_body
            write_page(paths, page)
    return {
        "scanned": len(files),
        "parsed": len(pages),
        "changed": changed,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="knowledge/novel-wiki")
    parser.add_argument("--apply", action="store_true", help="write the migration")
    args = parser.parse_args()
    paths = WikiPaths(Path(args.root).resolve())
    if not paths.wiki.exists():
        parser.error(f"wiki directory not found: {paths.wiki}")
    result = migrate(paths, apply=args.apply)
    mode = "APPLIED" if args.apply else "DRY-RUN"
    print(
        f"{mode}: scanned={result['scanned']} parsed={result['parsed']} "
        f"changed={result['changed']} errors={result['errors']}"
    )
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
