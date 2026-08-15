"""Scan and repair mojibake source files (GBK/Big5 misread through a single-byte codec).

Batch-50 finding (2026-08-15): 15 of 1358 novel-wiki raw files are
double-mojibake — the original GBK bytes were misinterpreted through a
single-byte codec (KOI8-U, KOI8-R, Latin-1, ...) and then re-saved as
UTF-8. Every one of them is a LARGE file (586KB–1.3MB), so they are the
highest-information documents in the pool and currently ingest as
garbage pages.

Repair chain (verified on the 586KB case):
    UTF-8 text → encode(source_codec) → decode(gbk|big5) → original CJK

Usage:
    python scripts/fix_mojibake_sources.py [--dir PATH] [--apply] [--min-cjk RATIO]

    --dir       directory to scan (default: knowledge/novel-wiki/raw/sources)
    --apply     actually rewrite repaired files (default: dry-run, only report)
    --min-cjk   CJK-density threshold below which a file is suspicious
                (default 0.25)

Dry-run output lists each suspicious file with its CJK density, the
repair verdict (REPAIRABLE with post-repair CJK density, or UNREPAIRABLE).
--apply rewrites repairable files in place as UTF-8 after verifying the
repair yields strong CJK (> 0.5). Unrepairable files are reported for
manual handling (they may need quarantine).
"""
import argparse
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.pipeline.collector import _decode_text_file, _repair_double_encoding


def cjk_ratio(text: str) -> float:
    total = len(text)
    if total == 0:
        return 0.0
    return sum(1 for c in text if "\u4e00" <= c <= "\u9fff") / total


def is_suspicious(raw: bytes, min_cjk: float) -> bool:
    """A file is suspicious when it decodes as UTF-8 but has almost no CJK."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return False  # not UTF-8 at all — collector already falls back to GBK
    total = len(text)
    if total < 200:
        return False
    return cjk_ratio(text) < min_cjk


def main() -> int:
    ap = argparse.ArgumentParser(description="Scan/repair mojibake source files")
    ap.add_argument("--dir", default="knowledge/novel-wiki/raw/sources")
    ap.add_argument("--apply", action="store_true", help="rewrite repaired files (default: dry-run)")
    ap.add_argument("--min-cjk", type=float, default=0.25)
    args = ap.parse_args()

    root = Path(args.dir)
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2

    repairable, unrepairable, clean = [], [], 0
    for f in sorted(root.rglob("*.md")):
        raw = f.read_bytes()
        if not is_suspicious(raw, args.min_cjk):
            clean += 1
            continue
        try:
            repaired = _decode_text_file(raw, str(f))
        except Exception as e:
            unrepairable.append((f, f"decode error: {e}", 0.0))
            continue
        rep_cjk = cjk_ratio(repaired)
        orig_cjk = cjk_ratio(raw.decode("utf-8", errors="replace"))
        if rep_cjk > 0.5:
            repairable.append((f, orig_cjk, rep_cjk, repaired))
        else:
            unrepairable.append((f, f"repair yielded {rep_cjk:.1%} CJK", rep_cjk))

    print(f"scanned {clean + len(repairable) + len(unrepairable)} files: "
          f"{clean} clean, {len(repairable)} repairable, {len(unrepairable)} unrepairable")

    if repairable:
        print("\n=== REPAIRABLE ===")
        for f, orig, rep, _ in repairable:
            print(f"  {f.relative_to(root)}  {orig:.0%} -> {rep:.0%} CJK")
        if args.apply:
            for f, orig, rep, repaired in repairable:
                # Keep \r\n style? Normalise to \n like _decode_text_file.
                f.write_bytes(repaired.encode("utf-8"))
                print(f"  [applied] rewrote {f.relative_to(root)} ({rep:.0%} CJK)")
        else:
            print("\n(dry-run — re-run with --apply to rewrite)")

    if unrepairable:
        print("\n=== UNREPAIRABLE (needs manual handling / quarantine) ===")
        for f, why, _ in unrepairable:
            print(f"  {f.relative_to(root)}  {why}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
