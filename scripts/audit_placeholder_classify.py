"""F3 — classify placeholder/stub pages in a wiki by id morphology.

Root-cause attribution support: the wiki's stub mechanism
(src/pipeline/ingest.py) creates a stub entity page for every slug that
was REFERENCED but neither produced this run nor existing on disk. The
stub id therefore mirrors the slug the LLM referenced — so the id
morphology tells us what kind of reference the Generator emitted.

Buckets (priority order, first match wins):
  raw_or_path  : id contains 'raw', '--' (double hyphen from path segs), or '-md-'
  tag_like     : starts with a known tag-namespace + '-'
  type_prefix  : starts with source-|concept-|synthesis-
  entity_suffix: ends with '-entity'
  source_like  : ends with an 8-hex hash (likely a BROKEN source-page slug guess)
  clean        : everything else (real entity referenced but not produced)

Usage:
  env PYTHONIOENCODING=utf-8 python scripts/audit_placeholder_classify.py <wiki_root> [sample_out]
Counts print as ASCII; up to 4 sample ids per bucket go to sample_out (UTF-8).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

TAG_NS = ("genre", "func", "char", "event", "mood", "entity", "scene_phase", "status")
TYPE_PFX = ("source", "concept", "synthesis")
HEX_TAIL = re.compile(r"-[0-9a-f]{8,}$")


def bucket(id_: str) -> str:
    if "raw" in id_ or "--" in id_ or "-md-" in id_:
        return "raw_or_path"
    if any(id_.startswith(p + "-") for p in TAG_NS):
        return "tag_like"
    if any(id_.startswith(p + "-") for p in TYPE_PFX):
        return "type_prefix"
    if id_.endswith("-entity"):
        return "entity_suffix"
    if HEX_TAIL.search(id_):
        return "source_like"
    return "clean"


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: audit_placeholder_classify.py <wiki_root> [sample_out]")
        sys.exit(2)
    root = Path(sys.argv[1])
    sample_out = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    entities_dir = root / "wiki" / "entities"

    counts: dict[str, int] = {}
    samples: dict[str, list[str]] = {}
    total_stubs = 0
    total_all = 0
    for f in entities_dir.glob("*.md"):
        total_all += 1
        text = f.read_text(encoding="utf-8", errors="replace")
        if "占位条目" not in text:
            continue
        total_stubs += 1
        id_ = f.stem
        b = bucket(id_)
        counts[b] = counts.get(b, 0) + 1
        samples.setdefault(b, []).append(f"{id_}  <-  {f.name}")

    print(f"entities_total      {total_all}")
    print(f"stub_pages          {total_stubs}")
    print("--- by id morphology ---")
    for b in ("raw_or_path", "tag_like", "type_prefix", "entity_suffix", "source_like", "clean"):
        print(f"{b:<15} {counts.get(b, 0)}")

    if sample_out:
        lines = []
        for b, ss in samples.items():
            lines.append(f"== {b} ({len(ss)}) ==")
            lines.extend(ss[:4])
            lines.append("")
        sample_out.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
