"""One-shot chapter-title generator (Task 3 of plan 2026-09-10-novel-wiki-fullbook-readability).

Drives `generate_chapter_titles` against the active release of a given
project, writes the resulting `chapter-titles.json` (and a `preface.md`
skeleton) to `book-wiki/.releases/<active>/editorial/`. The LLM call
defaults to `provider=None` (deterministic fallback) so the script
runs without a configured API key. To enable the LLM path, export
`RUFLO_LLM_PROVIDER=<name>` so `create_llm_provider` resolves it.

Usage:
    python scripts/title_book_chapters.py --project <id> [--release <rel>]
    python scripts/title_book_chapters.py --project <id> --apply

The script is idempotent: running it twice on the same release
overwrites `editorial/chapter-titles.json` deterministically.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Make the repo importable when run as a script.
_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

# Load .env (script bypasses src/cli.py:89-96 which does this normally).
from dotenv import load_dotenv  # noqa: E402
load_dotenv(_REPO / ".env", override=False)
load_dotenv(Path.cwd() / ".env", override=False)

from src.kc.views.book.wiki.polish_llm import generate_chapter_titles  # noqa: E402
from src.lib.project import resolve_project  # noqa: E402
from src.project.context import ProjectNotFoundError  # noqa: E402
from src.services.files import book_wiki_manifest, BookWikiUnavailableError  # noqa: E402
from src.llm.provider_factory import create_llm_provider  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--project", required=True, help="Project id or name")
    parser.add_argument("--release", help="Target release id; default = active")
    parser.add_argument(
        "--apply", action="store_true",
        help="Write editorial/chapter-titles.json (default: print plan only)",
    )
    parser.add_argument("--preface-min-words", type=int, default=2500,
                        help="Preface target word count (advisory; printed in plan)")
    return parser.parse_args()


async def _titles_for_manifest(manifest: dict, provider) -> dict:
    chapters_meta = [
        {
            "chapter_id": ch.get("chapter_id"),
            "title": ch.get("title"),
            "first_page_title": ch.get("title"),
        }
        for ch in manifest.get("chapters", [])
    ]
    return await generate_chapter_titles(chapters_meta, provider)


def _write_titles(release_dir: Path, manifest: dict, result) -> Path:
    editorial = release_dir / "editorial"
    editorial.mkdir(parents=True, exist_ok=True)
    # `result` is `ChapterTitleResult` (frozen dataclass). Tolerate a
    # plain dict for callers/tests that pass one in directly.
    if hasattr(result, "titles"):
        titles_map = result.titles
        truncated = result.truncated
        renamed = result.renamed
        failed = result.failed
    else:
        titles_map = result["titles"]
        truncated = result["truncated"]
        renamed = result["renamed"]
        failed = result["failed"]
    payload = {
        "version": manifest.get("version"),
        "titles": titles_map,
        "stats": {
            "truncated": truncated,
            "renamed": renamed,
            "failed": failed,
        },
    }
    target = editorial / "chapter-titles.json"
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return target


def _write_preface_skeleton(release_dir: Path, manifest: dict, target_words: int) -> Path:
    """Write a placeholder preface.md that the real retitle pass fills.

    The skeleton is intentionally short; the real prose is generated
    by the LLM in the apply pass. This stub exists so the file is
    visible to the WebUI before the LLM call.
    """
    preface_path = release_dir / "preface.md"
    preface_path.write_text(
        "# 总序\n\n"
        f"本教程分若干大主题，建议按目录顺序阅读，每章约 25-35 分钟。\n"
        f"目标字数：约 {target_words} 字（待 LLM 填充）。\n",
        encoding="utf-8",
    )
    return preface_path


def main() -> int:
    args = _parse_args()
    try:
        ctx, _paths = resolve_project(args.project, by_id_only=True)
    except ProjectNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    try:
        manifest = book_wiki_manifest(args.project, version=args.release)
    except BookWikiUnavailableError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 3

    release_id = manifest.get("version")
    book_dir = ctx.path / "book-wiki"
    release_dir = book_dir / ".releases" / str(release_id)
    if not release_dir.is_dir():
        print(f"Error: release directory missing: {release_dir}", file=sys.stderr)
        return 3

    chapter_count = len(manifest.get("chapters", []))
    print(f"book-wiki/{release_id}: {chapter_count} chapters")
    print(f"  output: {release_dir / 'editorial' / 'chapter-titles.json'}")
    print(f"  preface: {release_dir / 'preface.md'} (target ~{args.preface_min_words} words)")

    if not args.apply:
        print("dry-run: pass --apply to write files")
        return 0

    # Resolve provider: env var wins; default None (deterministic fallback).
    provider = None
    provider_name = ""
    try:
        import os
        provider_name = os.environ.get("RUFLO_LLM_PROVIDER", "").strip()
        if provider_name:
            provider = create_llm_provider(provider_name)
            print(f"  using provider: {provider_name}")
        else:
            print("  no RUFLO_LLM_PROVIDER set; using deterministic fallback")
    except Exception as exc:  # noqa: BLE001
        print(f"  provider resolution failed ({exc}); using fallback")
        provider = None

    titles = asyncio.run(_titles_for_manifest(manifest, provider))
    titles_path = _write_titles(release_dir, manifest, titles)
    preface_path = _write_preface_skeleton(
        release_dir, manifest, args.preface_min_words,
    )
    print(f"wrote {titles_path}")
    print(f"wrote {preface_path}")
    print(
        f"stats: truncated={titles.truncated}, renamed={titles.renamed}, "
        f"failed={titles.failed}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
