"""One-shot validation of programmatic run_ingest → perf-test.

Ingests a single source doc from novel-wiki raw/sources into the
perf-test project via the minimax provider. Instruments stage timings.
"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.lib.project import resolve_project
from src.llm.provider_factory import create_llm_provider


def main() -> None:
    perf_id = "b35ad019-8fbf-4cf0-bbf0-aeec1af0f248"
    ctx, paths = resolve_project(perf_id, by_id_only=True)
    print(f"[validate] project resolved: {ctx.name} ({ctx.id})")
    print(f"[validate] wiki roots: sources={paths.wiki_sources}")

    # Pick a small, representative source doc.
    novel_sources = Path(r"D:\5-Project\LLM-Wiki-7-31\LLM-Wiki\knowledge\novel-wiki\raw\sources")
    candidates = sorted(novel_sources.rglob("*.md"))
    print(f"[validate] novel-wiki source count: {len(candidates)}")
    if not candidates:
        print("FATAL: no sources in novel-wiki raw/sources")
        sys.exit(1)

    # Prefer a small file (< 8KB) so the first run is fast.
    small = [c for c in candidates if c.stat().st_size < 8192]
    pick = small[0] if small else candidates[0]
    text = pick.read_text(encoding="utf-8", errors="replace")
    print(f"[validate] picked source: {pick.relative_to(novel_sources)} ({len(text)} chars)")

    provider = create_llm_provider("minimax")
    print(f"[validate] provider: minimax ({type(provider).__name__})")

    from src.pipeline.ingest import run_ingest

    async def _run():
        t0 = time.monotonic()
        pages = await run_ingest(
            paths=paths,
            source_path=str(pick),
            source_text=text,
            provider=provider,
            folder_context="",
            task_id="perf-validate",
        )
        elapsed = time.monotonic() - t0
        return pages, elapsed

    pages, elapsed = asyncio.run(_run())
    print(f"[validate] DONE in {elapsed:.2f}s, {len(pages)} page(s)")
    for p in pages:
        t = p.type.value if hasattr(p.type, "value") else str(p.type)
        print(f"  - [{t}] {p.title} (grade={p.grade})")


if __name__ == "__main__":
    main()
