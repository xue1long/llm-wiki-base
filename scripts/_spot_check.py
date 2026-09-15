"""Real-LLM spot-check for v3.0 pipeline.

Loads the original 10-sample spot-check fixture, runs Stage 1 (classify)
against MiniMax-M3, and reports accuracy.

This is the v2 spot-check resurrected under the v3 async API. The
underlying LLM is the same (MiniMax-M3); the difference is that
v3 uses async + FakeLLMClient-compatible code paths.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.pipeline.v7_extract.doc_classifier import classify_doc
from src.pipeline.v7_extract.llm_client import AnthropicLLMClient


# 10 samples from the original 2026-09-13 v2 spot-check report.
# Each entry: (source_path, expected_doc_type).
SPOT_CHECK = [
    ("raw/sources/01_新手入门/借鉴素材小说写作.md", "multi_section"),
    ("raw/sources/01_新手入门/入门教程一个新手的五个阶段.md", "multi_section"),
    ("raw/sources/01_新手入门/入门教程三江.md", "incomplete"),
    ("raw/sources/01_新手入门/入门教程人物代入感方面的刻画.md", "single_method"),
    ("raw/sources/01_新手入门/入门教程作家是怎么炼成的新手必看.md", "single_method"),
    ("raw/sources/01_新手入门/入门教程基础篇语言规范.md", "single_method"),
    ("raw/sources/01_新手入门/入门教程网络小说写作宝典.md", "single_method"),
    ("raw/sources/01_新手入门/入门教程谈谈小说的矛盾冲突大高潮小高潮如何营造及小说节奏.md", "multi_section"),
    ("raw/sources/01_新手入门/必备资料11月28号创酷中文网女频现言讲课记录_8c363e.md", "qa_chat"),
    ("raw/sources/01_新手入门/必备资料20个签约条件新人必看2.md", "list"),
]


async def run_one(llm, rel_path: str, expected: str) -> tuple[str, str, bool]:
    """Return (rel_path, predicted, correct)."""
    full = _REPO_ROOT / "knowledge" / "novel-wiki" / rel_path
    if not full.is_file():
        return rel_path, "MISSING_FILE", False
    content = full.read_text(encoding="utf-8", errors="replace")[:4000]
    classification = await classify_doc(
        content,
        filename_hint=full.name,
        llm=llm,
        project_root=_REPO_ROOT,
    )
    return rel_path, classification.doc_type, classification.doc_type == expected


async def main() -> int:
    llm = AnthropicLLMClient(default_provider_name="minimax")
    print(f"provider: {llm.provider_name}")
    print(f"running {len(SPOT_CHECK)} spot-check samples against MiniMax-M3")
    print()

    results = []
    for rel_path, expected in SPOT_CHECK:
        rel, predicted, correct = await run_one(llm, rel_path, expected)
        marker = "OK" if correct else "MISS"
        print(f"  [{marker}] expected={expected:<15} predicted={predicted:<15}  {rel}")
        results.append(correct)

    print()
    correct_count = sum(results)
    print(f"accuracy: {correct_count}/{len(results)} = {correct_count * 100 // len(results)}%")
    return 0 if correct_count >= len(results) * 0.8 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
