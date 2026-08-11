"""Re-ingest test: verify fixes for body quality.

Run: PYTHONPATH=. python test_reingest.py
"""
import asyncio
import os
import re
import sys
from pathlib import Path

project_id = "c3e70991-26fe-4546-8321-cf33ceb4c6e6"

# Use a specific known file
source_dir = Path(r"D:\5-Project\llm-wiki-base\knowledge\novel-wiki\raw\sources\01_新手入门")

# Pick a file that's medium-sized and has good content - avoid the repetitive one
# Let's try one around 3-10KB that isn't tagged as repetitive
files = list(source_dir.iterdir())
# Sort by size, pick one around 4-10KB
candidates = [(f, f.stat().st_size) for f in files if 2000 <= f.stat().st_size <= 12000]
candidates.sort(key=lambda x: x[1])
# Pick one from the middle
test_file = candidates[len(candidates) // 2][0]

print(f"Selected: {test_file.name} ({test_file.stat().st_size} bytes)")

source_text = test_file.read_text(encoding="utf-8")
print(f"Source text length: {len(source_text)} chars")
# Safe print - handle non-GBK chars
safe_first = source_text[:200].encode('utf-8', errors='replace').decode('utf-8', errors='replace')
print(f"First 200 chars: {safe_first}")
print(f"---")

from src.pipeline import _resolve_wiki_paths, _get_provider, run_ingest

paths = _resolve_wiki_paths(project_id)
print(f"Wiki paths root: {paths.root}")

provider = _get_provider(project_id)
print(f"Provider model: {provider.model}")

# source_path must be project-relative so the reviewer's reference check
# (project_path / source_path) resolves to a real file.
relative_source = test_file.relative_to(paths.root)
print(f"Relative source path: {relative_source}")

async def test():
    try:
        pages = await run_ingest(
            paths=paths,
            source_path=relative_source,
            source_text=source_text,
            provider=provider,
            task_id="test-reingest-fixes",
        )
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return

    print(f"Generated {len(pages)} page(s):")
    for p in pages:
        print(f"--- Page: {p.title} (id={p.id}, grade={p.grade}, type={p.type}) ---")
        print(f"  Body length: {len(p.body)}")
        # Check for missing placeholders
        has_missing = "（待补充）" in p.body
        has_system = "（系统占位" in p.body
        print(f"  Has '待补充': {has_missing}")
        print(f"  Has system placeholder: {has_system}")
        # Show body content with slot markers
        slot_markers = re.findall(r'<!-- slot:(\w+) -->\s*(.*?)(?=\n## |<!-- slot:|$)', p.body, re.DOTALL)
        if slot_markers:
            print(f"  Slots ({len(slot_markers)}):")
            for slot_name, slot_content in slot_markers:
                content = slot_content.strip()
                preview = content[:200].replace('\n', '\\n')
                print(f"    {slot_name}: {len(content)} chars -> {preview}")
        else:
            # No slot markers - show first 300 chars of body
            print(f"  Body preview: {p.body[:300]}")

asyncio.run(test())