"""Stage1/3/4 offline precomputation for AGL training.

Ponytail: this runs Stage1/3/4 with frozen LLM (no AGL Gateway),
producing a JSONL of (raw_path, topic) pairs that the AGL trainer reads
to enqueue one rollout per topic.

Output schema (one JSON object per line):
    {"raw_path": str, "topic_id": str, "title": str, "sources": list[str]}

Usage:
    python -m src.v7_agl.precompute_topics \\
        --raw-dir knowledge/novel-wiki/raw/sources \\
        --out knowledge/novel-wiki/.index/agl/experiments/smoke/precomputed_topics.jsonl
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path


# Force V2 fill_slots path (the AGL agent only trains V2).
os.environ.setdefault("V7_USE_V3", "false")


async def _precompute_one(raw_path: Path) -> list[dict]:
    """Run Stage1/3/4 on one raw file; return list of topic dicts.

    Returns [] on technical failure (D7 contract).
    """
    from src.pipeline.v7_extract.doc_classifier import classify_doc
    from src.pipeline.v7_extract.completeness_checker import check_completeness
    from src.pipeline.v7_extract.topic_clusterer import cluster_topics

    raw_text = raw_path.read_text(encoding="utf-8", errors="ignore")
    doc_type = await classify_doc(raw_text, filename_hint=raw_path.name)
    is_complete, _ = await check_completeness(raw_text, doc_type=doc_type)
    if not is_complete:
        return []
    topics = await cluster_topics(raw_text, doc_type=doc_type)
    return [
        {
            "raw_path": str(raw_path),
            "topic_id": t.id,
            "title": t.title,
            "sources": list(getattr(t, "item_ids", []) or []),
        }
        for t in topics
    ]


async def _main(raw_dir: Path, out: Path, max_files: int | None) -> int:
    """Precompute topics for every raw .md under raw_dir."""
    from src.llm.registry import ProviderRegistry

    # Resolve default once; the offline run uses the project's regular LLM.
    try:
        ProviderRegistry.get_default()
    except Exception as exc:
        raise SystemExit(
            f"No default LLM provider configured: {exc!r}. "
            "Run `python -m src.cli llm-providers add ...` first."
        )

    out.parent.mkdir(parents=True, exist_ok=True)
    raws = sorted(p for p in raw_dir.rglob("*.md") if p.is_file())
    if max_files is not None:
        raws = raws[:max_files]

    written = 0
    with out.open("w", encoding="utf-8") as fh:
        for raw_path in raws:
            try:
                topics = await _precompute_one(raw_path)
            except Exception as exc:
                print(f"[skip] {raw_path}: {exc!r}")
                continue
            for topic in topics:
                fh.write(json.dumps(topic, ensure_ascii=False) + "\n")
                written += 1

    print(f"Wrote {written} topics from {len(raws)} raw files -> {out}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-files", type=int, default=None)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_main(args.raw_dir, args.out, args.max_files)))


if __name__ == "__main__":
    main()