"""pilot_ingest.py — Phase 4.2 pilot: re-ingest N random unreferenced raw files.

Reads the backlog manifest produced by build_reingest_backlog.py, picks N
random files, drives run_ingest through the production provider/wiki-path
resolution, and reports per-file page/stub/error counts to stdout AND a
report file (default: scripts/_pilot_report.txt).

Usage:
    env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
      PYTHONIOENCODING=utf-8 PYTHONPATH=. python scripts/pilot_ingest.py \
      --project 8dd46257-e46d-4bf8-b8d8-ba60b2aea54d --count 10
"""
from __future__ import annotations

import argparse
import asyncio
import random
import sys
import time
from pathlib import Path

from _common import log_message

PROJECT_ID = "8dd46257-e46d-4bf8-b8d8-ba60b2aea54d"
ROOT = Path("knowledge/novel-wiki")
MANIFEST = ROOT / ".index" / "reingest_backlog.json"
REPORT = Path("scripts/_pilot_report.txt")


def _log(msg: str) -> None:
    log_message(msg, REPORT)


async def _run_one(paths, provider, raw_rel: str, task_id: str) -> str:
    from src.pipeline import run_ingest
    src = ROOT / raw_rel
    if not src.is_file():
        return f"SKIP missing: {raw_rel}"
    text = src.read_text(encoding="utf-8", errors="replace")
    # FIX: source_path must be PROJECT-RELATIVE (`raw/sources/...`), the exact
    # form production passes. `str()` of a Windows Path gives backslashes
    # (`raw\sources\...`) which is what the source-slug md5 + `sources` field
    # expect — passing the CWD-relative path produced non-canonical slugs.
    pages = await run_ingest(
        paths=paths,
        source_path=Path(raw_rel),
        source_text=text,
        provider=provider,
        folder_context="",
        task_id=task_id,
    )
    stubs = [p for p in pages if getattr(p, "processing_depth", "") == "stub"]
    by_type: dict[str, int] = {}
    for p in pages:
        by_type[p.type.value] = by_type.get(p.type.value, 0) + 1
    tags_ugc = sum(1 for p in pages if "素材/ugc" in getattr(p, "tags", []) or "可信度/ugc" in getattr(p, "tags", []))
    return (
        f"{raw_rel} -> {len(pages)} pages {by_type} "
        f"| stubs={len(stubs)} ugc_tags={tags_ugc}"
    )


async def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 4.2 pilot re-ingest (random sample).")
    ap.add_argument("--project", default=PROJECT_ID)
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--seed", type=int, default=None,
                    help="random seed (default: from os, truly random)")
    ap.add_argument("--report", default=str(REPORT))
    args = ap.parse_args()

    if not MANIFEST.exists():
        print(f"manifest missing: {MANIFEST} — run build_reingest_backlog.py --out first")
        return 1
    import json
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    files = [f for b in data["batches"] for f in b["files"]]
    if not files:
        print("backlog empty — nothing to ingest")
        return 1

    rng = random.Random(args.seed)
    sample = rng.sample(files, min(args.count, len(files)))
    _log(f"pilot: {len(sample)} files from {len(files)}-file backlog (seed={args.seed!r})")

    from src.pipeline import _get_provider, _resolve_wiki_paths
    paths = _resolve_wiki_paths(args.project)
    provider = _get_provider(args.project)
    _log(f"provider resolved: {type(provider).__name__}")

    ok = err = 0
    t0 = time.time()
    for i, raw_rel in enumerate(sample, 1):
        task_id = f"pilot-{Path(raw_rel).stem[:40]}"
        _log(f"[{i}/{len(sample)}] ingesting {raw_rel}")
        try:
            msg = await _run_one(paths, provider, raw_rel, task_id)
            _log(msg)
            ok += 1
        except Exception as exc:
            _log(f"ERROR {raw_rel}: {type(exc).__name__}: {exc}")
            err += 1
    _log(f"DONE ok={ok} err={err} elapsed={time.time()-t0:.0f}s")
    return 0 if err == 0 else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
