"""phase4_batch.py — Phase 4: ingest one backlog batch, then run the quality gate.

Consumes the backlog manifest from build_reingest_backlog.py, ingests one
batch's files through run_ingest (production provider/paths, canonical
project-relative source_path — no server needed), then runs the per-batch
gate (batch_gate_check) on the batch's new/updated pages.

Distinct from scripts/batch_ingest.py (prior-session, HTTP-API folder/file
mode) — this one is the manifest + gate pipeline the plan's Phase 4.2 uses.

Usage:
    env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
      PYTHONIOENCODING=utf-8 PYTHONPATH=. python scripts/phase4_batch.py \
      --batch 0 [--count 10] [--skip-gate]

Exit code: 0 = batch ingested and gate passed; 2 = gate violations.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

PROJECT_ID = "8dd46257-e46d-4bf8-b8d8-ba60b2aea54d"
ROOT = Path("knowledge/novel-wiki")
MANIFEST = ROOT / ".index" / "reingest_backlog.json"
REPORT = Path("scripts/_batch_report.txt")

_TYPE_DIR = {"source": "sources", "entity": "entities",
             "concept": "concepts", "synthesis": "synthesis"}


def _log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with REPORT.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


async def main() -> int:
    ap = argparse.ArgumentParser(description="Ingest one backlog batch + gate.")
    ap.add_argument("--manifest", default=str(MANIFEST))
    ap.add_argument("--batch", type=int, default=0, help="batch index in manifest")
    ap.add_argument("--count", type=int, default=None, help="limit files in this run")
    ap.add_argument("--project", default=PROJECT_ID)
    ap.add_argument("--skip-gate", action="store_true")
    args = ap.parse_args()

    if not Path(args.manifest).exists():
        print(f"manifest missing: {args.manifest} — run build_reingest_backlog.py --out first")
        return 1
    data = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    batches = data["batches"]
    if args.batch >= len(batches):
        print(f"batch {args.batch} out of range (0..{len(batches)-1})")
        return 1
    batch = batches[args.batch]
    files = batch["files"]
    if args.count is not None:
        files = files[: args.count]
    _log(f"batch {args.batch} [{batch['theme']}]: {len(files)} file(s)")

    from src.pipeline import _get_provider, _resolve_wiki_paths, run_ingest
    paths = _resolve_wiki_paths(args.project)
    provider = _get_provider(args.project)
    _log(f"provider: {type(provider).__name__}")

    created_paths: list[Path] = []
    ok = err = 0
    t0 = time.time()
    for raw_rel in files:
        src = ROOT / raw_rel
        if not src.is_file():
            _log(f"SKIP missing: {raw_rel}")
            continue
        text = src.read_text(encoding="utf-8", errors="replace")
        task_id = f"b{args.batch}-{Path(raw_rel).stem[:30]}"
        _log(f"[{ok+err+1}/{len(files)}] {raw_rel}")
        try:
            pages = await run_ingest(
                paths=paths, source_path=Path(raw_rel), source_text=text,
                provider=provider, folder_context="", task_id=task_id,
            )
            for p in pages:
                d = _TYPE_DIR.get(p.type.value)
                if d:
                    created_paths.append(Path("wiki") / d / f"{p.id}.md")
            stubs = sum(1 for p in pages if getattr(p, "processing_depth", "") == "stub")
            _log(f"  -> {len(pages)} pages, stubs={stubs}")
            ok += 1
        except Exception as exc:
            _log(f"  ERROR: {type(exc).__name__}: {exc}")
            err += 1
    _log(f"ingested ok={ok} err={err} elapsed={time.time()-t0:.0f}s")

    gate_rc = 0
    if not args.skip_gate and created_paths:
        from scripts.batch_gate_check import check_page
        violations: list[str] = []
        for rel in created_paths:
            p = ROOT / rel
            if not p.is_file():
                violations.append(f"MISSING: {rel}")
                continue
            violations.extend(check_page(p))
        _log(f"gate: {len(created_paths)} batch page(s), {len(violations)} violation(s)")
        for v in violations:
            _log(f"  GATE {v}")
        gate_rc = 1 if violations else 0

    _log(f"BATCH DONE ok={ok} err={err} gate={'PASS' if gate_rc == 0 else 'FAIL'}")
    return 2 if gate_rc else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
