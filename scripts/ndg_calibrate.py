"""ndg_calibrate.py — NDG Phase 0: dry-run sample, collect metrics, lock thresholds.

Samples N raw files, runs ``generate_ingest`` (dry — NO disk writes),
collects ``_long_raw_text_run`` distributions and fulltext-section hits,
then outputs a calibration report.  Optionally writes the calibrated
``T_source`` / ``T_non`` thresholds to ``.index/quality_settings.json``.

Usage:
    # From backlog manifest (preferred):
    env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
      PYTHONIOENCODING=utf-8 PYTHONPATH=. python scripts/ndg_calibrate.py \
      --manifest knowledge/novel-wiki/.index/reingest_backlog.json \
      --project <id> --sample 25 --seed 42

    # From a directory of raw files (fallback):
    env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
      PYTHONIOENCODING=utf-8 PYTHONPATH=. python scripts/ndg_calibrate.py \
      --raw-dir knowledge/novel-wiki/raw/sources \
      --project <id> --sample 25

    # Write calibrated thresholds:
    ... --write-thresholds

Report saved to ``scripts/_ndg_calibrate_report.txt``.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

PROJECT_ID = "8dd46257-e46d-4bf8-b8d8-ba60b2aea54d"
ROOT = Path("knowledge/novel-wiki")
REPORT_PATH = Path("scripts/_ndg_calibrate_report.txt")


def _log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)


def _pct(sorted_vals: list[int], p: float) -> float:
    """Return the p-th percentile of *sorted_vals* (0.0–1.0)."""
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * p
    f = int(k)
    c = k - f
    if f + 1 < len(sorted_vals):
        return sorted_vals[f] * (1 - c) + sorted_vals[f + 1] * c
    return float(sorted_vals[f])


def _round_up_to(v: float, multiple: int = 50) -> int:
    """Round *v* up to the nearest *multiple*."""
    return int(((int(v) + multiple - 1) // multiple) * multiple)


def _histogram_bucket(v: int, bin_size: int = 200) -> str:
    """Return a label like '0-200' or '2000+' for histogram display."""
    lo = (v // bin_size) * bin_size
    hi = lo + bin_size
    return f"{lo}-{hi}"


def _histogram(values: list[int], bin_size: int = 200) -> dict[str, int]:
    """Build a binned histogram of *values*."""
    bins: dict[str, int] = defaultdict(int)
    for v in values:
        bins[_histogram_bucket(v, bin_size)] += 1
    return dict(sorted(bins.items(),
                       key=lambda x: int(x[0].split("-")[0]) if x[0][0].isdigit() else 0))


def _scan_raw_files(raw_dir: Path, max_files: int | None = None) -> list[Path]:
    """Scan *raw_dir* recursively for readable text files."""
    files: list[Path] = []
    for ext in ("*.txt", "*.md", "*.html"):
        for f in raw_dir.rglob(ext):
            if f.is_file():
                files.append(f)
    files.sort()
    if max_files is not None:
        files = files[:max_files]
    return files


async def main() -> int:
    ap = argparse.ArgumentParser(description="NDG Phase 0: calibrate RAW-PASTE thresholds")
    ap.add_argument("--manifest", default=None)
    ap.add_argument("--raw-dir", default=None)
    ap.add_argument("--project", default=PROJECT_ID)
    ap.add_argument("--sample", type=int, default=25)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--write-thresholds", action="store_true")
    ap.add_argument("--report", default=str(REPORT_PATH))
    args = ap.parse_args()

    # ── Resolve input files ─────────────────────────────────────────
    raw_files: list[Path] = []
    if args.manifest:
        mp = Path(args.manifest)
        if not mp.exists():
            _log(f"manifest not found: {mp}")
            return 1
        data = json.loads(mp.read_text(encoding="utf-8"))
        # Collect from all batches
        for batch in data.get("batches", []):
            for f_rel in batch.get("files", []):
                raw_files.append(ROOT / f_rel)
        _log(f"loaded {len(raw_files)} file(s) from manifest")
    elif args.raw_dir:
        rd = Path(args.raw_dir)
        if not rd.is_dir():
            _log(f"raw-dir not found: {rd}")
            return 1
        raw_files = _scan_raw_files(rd)
        _log(f"scanned {len(raw_files)} file(s) from {rd}")
    else:
        _log("ERROR: --manifest or --raw-dir required")
        return 1

    if not raw_files:
        _log("ERROR: no raw files found")
        return 1

    # ── Sample ──────────────────────────────────────────────────────
    rng = random.Random(args.seed)
    sample = rng.sample(raw_files, min(args.sample, len(raw_files)))
    _log(f"sampled {len(sample)}/{len(raw_files)} file(s) (seed={args.seed})")

    # ── Resolve provider + paths ────────────────────────────────────
    from src.pipeline import _get_provider, _resolve_wiki_paths
    from src.pipeline.ingest import generate_ingest
    from src.wiki.features.lint import _long_raw_text_run, _has_fulltext_section

    paths = _resolve_wiki_paths(args.project)
    provider = _get_provider(args.project)
    _log(f"provider: {type(provider).__name__}")

    # ── Dry-run generate for each sample file ───────────────────────
    # Per-page metrics collected across all files.
    all_runs: list[int] = []           # _long_raw_text_run values
    source_runs: list[int] = []        # runs for SOURCE pages only
    non_source_runs: list[int] = []    # runs for non-SOURCE pages
    body_chars: list[int] = []         # len(body)
    fulltext_hits: list[str] = []      # page_ids with fulltext section headings
    page_types: dict[str, int] = defaultdict(int)  # type → count
    file_count = 0
    page_count = 0
    errors = 0

    t0 = time.time()
    for sp in sample:
        try:
            text = sp.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            _log(f"SKIP {sp.name}: {exc}")
            errors += 1
            continue

        task_id = f"calib-{sp.stem[:30]}"
        _log(f"[{file_count+1}/{len(sample)}] {sp.name}")

        try:
            pages, extra, meta = await generate_ingest(
                paths=paths, source_path=sp, source_text=text,
                provider=provider, folder_context="", task_id=task_id,
            )
        except Exception as exc:
            _log(f"  ERROR: {type(exc).__name__}: {exc}")
            errors += 1
            continue

        file_count += 1
        for p in pages:
            page_count += 1
            run = _long_raw_text_run(p.body)
            chars = len(p.body)
            all_runs.append(run)
            body_chars.append(chars)
            type_str = p.type.value if hasattr(p.type, "value") else str(p.type)
            page_types[type_str] += 1

            if p.type.value == "source" if hasattr(p.type, "value") else p.type == "source":
                source_runs.append(run)
            else:
                non_source_runs.append(run)

            if _has_fulltext_section(p.body):
                fulltext_hits.append(p.id)

        stubs = sum(1 for p in pages if getattr(p, "processing_depth", "") == "stub")
        _log(f"  -> {len(pages)} pages, stubs={stubs}, "
             f"rejected={meta.get('rejected')}")

    elapsed = time.time() - t0
    _log(f"done: {file_count} files → {page_count} pages, "
         f"errors={errors}, elapsed={elapsed:.0f}s")

    if page_count == 0:
        _log("ERROR: no pages generated — cannot calibrate")
        return 1

    # ── Build calibration report ────────────────────────────────────
    all_runs.sort()
    source_runs.sort()
    non_source_runs.sort()

    lines: list[str] = []
    lines.append("=" * 60)
    lines.append("NDG Phase 0 — Calibration Report")
    lines.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Sample: {file_count} files → {page_count} pages (errors={errors})")
    lines.append(f"Seed: {args.seed}")
    lines.append("=" * 60)
    lines.append("")

    # Page type distribution
    lines.append("## Page type distribution")
    for pt, cnt in sorted(page_types.items(), key=lambda x: -x[1]):
        lines.append(f"  {pt}: {cnt}")
    lines.append("")

    # Fulltext section hits
    lines.append(f"## Fulltext-section headings: {len(fulltext_hits)} hit(s)")
    if fulltext_hits:
        for pid in fulltext_hits[:20]:
            lines.append(f"  - {pid}")
    lines.append("")

    # _long_raw_text_run distribution
    lines.append("## _long_raw_text_run distribution (all pages)")
    lines.append(f"  count : {len(all_runs)}")
    lines.append(f"  min   : {min(all_runs) if all_runs else 0}")
    lines.append(f"  p50   : {_pct(all_runs, 0.50):.0f}")
    lines.append(f"  p90   : {_pct(all_runs, 0.90):.0f}")
    lines.append(f"  p95   : {_pct(all_runs, 0.95):.0f}")
    lines.append(f"  p99   : {_pct(all_runs, 0.99):.0f}")
    lines.append(f"  max   : {max(all_runs) if all_runs else 0}")
    lines.append("")

    lines.append("## SOURCE pages")
    lines.append(f"  count : {len(source_runs)}")
    lines.append(f"  p90   : {_pct(source_runs, 0.90):.0f}")
    lines.append(f"  p95   : {_pct(source_runs, 0.95):.0f}")
    lines.append(f"  p99   : {_pct(source_runs, 0.99):.0f}")
    lines.append(f"  max   : {max(source_runs) if source_runs else 0}")
    lines.append("")

    lines.append("## Non-SOURCE pages")
    lines.append(f"  count : {len(non_source_runs)}")
    lines.append(f"  p90   : {_pct(non_source_runs, 0.90):.0f}")
    lines.append(f"  p95   : {_pct(non_source_runs, 0.95):.0f}")
    lines.append(f"  p99   : {_pct(non_source_runs, 0.99):.0f}")
    lines.append(f"  max   : {max(non_source_runs) if non_source_runs else 0}")
    lines.append("")

    # Histogram
    lines.append("## Run-length histogram (all pages, bin=200)")
    hist = _histogram(all_runs, 200)
    max_count = max(hist.values()) if hist else 1
    for bucket, count in hist.items():
        bar = "#" * max(1, count * 40 // max_count)
        lines.append(f"  {bucket:>10}: {bar} ({count})")
    lines.append("")

    # Top-10 longest runs
    lines.append("## Top-10 longest _long_raw_text_run (for human review)")
    lines.append("  (Judge: 'legitimate long summary' vs 'raw paste pollution')")
    top_runs = sorted(all_runs, reverse=True)[:10]
    for i, r in enumerate(top_runs, 1):
        lines.append(f"  {i:>2}. {r} chars")
    lines.append("")

    # Body chars distribution
    body_chars.sort()
    lines.append("## Body character count distribution")
    lines.append(f"  p50 : {_pct(body_chars, 0.50):.0f}")
    lines.append(f"  p90 : {_pct(body_chars, 0.90):.0f}")
    lines.append(f"  p99 : {_pct(body_chars, 0.99):.0f}")
    lines.append("")

    # ── Proposed thresholds ─────────────────────────────────────────
    # Source pages: p99 of source runs, rounded up to 50.
    # Non-source pages: p99 of non-source runs, rounded up to 50.
    # Floor: never go below the internal defaults.
    from src.wiki.features.lint import _DEFAULT_T_SOURCE, _DEFAULT_T_NON

    proposed_T_source = max(
        _DEFAULT_T_SOURCE,
        _round_up_to(_pct(source_runs, 0.99), 50) if source_runs else _DEFAULT_T_SOURCE,
    )
    proposed_T_non = max(
        _DEFAULT_T_NON,
        _round_up_to(_pct(non_source_runs, 0.99), 50) if non_source_runs else _DEFAULT_T_NON,
    )

    lines.append("## Proposed thresholds (p99 rounded up to 50)")
    lines.append(f"  T_source (source pages)        : {proposed_T_source}")
    lines.append(f"  T_non   (non-source pages)     : {proposed_T_non}")
    lines.append(f"  (internal defaults for reference: T_source={_DEFAULT_T_SOURCE}, "
                 f"T_non={_DEFAULT_T_NON})")
    lines.append("")

    # ── Quality checks ──────────────────────────────────────────────
    lines.append("## Sanity checks")
    # P2 false-positive risk: how many pages would be flagged by proposed thresholds?
    source_flagged = sum(1 for r in source_runs if r > proposed_T_source)
    non_source_flagged = sum(1 for r in non_source_runs if r > proposed_T_non)
    lines.append(f"  Source pages flagged (run > {proposed_T_source}): "
                 f"{source_flagged}/{len(source_runs) if source_runs else 0}")
    lines.append(f"  Non-source flagged  (run > {proposed_T_non}):   "
                 f"{non_source_flagged}/{len(non_source_runs) if non_source_runs else 0}")
    lines.append(f"  Fulltext-section headings flagged: {len(fulltext_hits)}")
    lines.append("")
    lines.append("=" * 60)

    report = "\n".join(lines)
    print(report)

    # Write to report file
    args.report = Path(args.report)
    args.report.write_text(report + "\n", encoding="utf-8")
    _log(f"report saved to {args.report}")

    # ── Optionally write thresholds ─────────────────────────────────
    if args.write_thresholds:
        settings_path = paths.index / "quality_settings.json"
        existing: dict = {}
        if settings_path.exists():
            try:
                existing = json.loads(settings_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                existing = {}
        if not isinstance(existing, dict):
            existing = {}

        existing["raw_paste"] = {
            "source_threshold": proposed_T_source,
            "non_source_threshold": proposed_T_non,
            "calibrated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "calibration_sample": file_count,
            "calibration_seed": args.seed,
        }

        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        _log(f"thresholds written to {settings_path}")
        _log(f"  raw_paste.source_threshold = {proposed_T_source}")
        _log(f"  raw_paste.non_source_threshold = {proposed_T_non}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
