"""build_reingest_backlog.py — Phase 4.1: raw files not yet referenced by any
wiki page's ``sources`` field, grouped by theme and batched ≤20 for re-ingest.

Read-only: never writes wiki data. With ``--out`` it writes a JSON batch
manifest a batch-runner can consume (a new file, not wiki state).

Usage:
    env PYTHONIOENCODING=utf-8 python scripts/build_reingest_backlog.py [wiki_root]
    env PYTHONIOENCODING=utf-8 python scripts/build_reingest_backlog.py [wiki_root] --out backlog.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

WIKI_SUBDIRS = ("sources", "entities", "concepts", "synthesis")
# Only files the ingest collector can actually process count toward the
# re-ingest backlog; skip obvious non-document artifacts.
INCLUDE_SUFFIXES = {".md", ".txt", ".pdf", ".docx", ".xlsx", ".html", ".htm", ".epub"}
BATCH_SIZE = 20


def _frontmatter_sources(text: str) -> list[str]:
    """Return the ``sources:`` list values from a page's frontmatter."""
    m = re.search(r"(?ms)^sources:\s*(.*?)(?=^[a-z_]+:|\Z)", text)
    if not m:
        return []
    block = m.group(1)
    out: list[str] = []
    for line in block.split("\n"):
        s = line.strip()
        if s.startswith("- "):
            out.append(s[2:].strip().strip('"').strip("'"))
    return out


def _norm(raw: str) -> str:
    """Normalise a stored source path to project-relative posix form.

    Stored values look like ``raw\\sources\\01_新手入门\\x.md`` (Windows
    backslashes, ``raw`` prefix) or ``raw/sources/...``. Returns
    ``sources/01_新手入门/x.md`` (raw/ prefix stripped).
    """
    s = raw.replace("\\", "/").strip()
    if s.startswith("raw/"):
        s = s[len("raw/"):]
    return s


def main() -> int:
    ap = argparse.ArgumentParser(
        description="List unreferenced raw files and group them into ≤20-file batches.",
    )
    ap.add_argument("wiki_root", nargs="?", default="knowledge/novel-wiki",
                    help="project root (parent of raw/ and wiki/). default: knowledge/novel-wiki")
    ap.add_argument("--out", default=None,
                    help="write the batch manifest JSON to this path (default: stdout preview only)")
    ap.add_argument("--batch", type=int, default=BATCH_SIZE,
                    help=f"max files per batch (default {BATCH_SIZE})")
    args = ap.parse_args()

    root = Path(args.wiki_root)
    raw_root = root / "raw"
    wiki_root = root / "wiki"

    raw_files = sorted(
        p for p in raw_root.rglob("*")
        if p.is_file() and p.suffix.lower() in INCLUDE_SUFFIXES
    )
    if not raw_files:
        print(f"[backlog] no ingestible raw files under {raw_root}")
        return 1

    # Every raw path referenced by any wiki page's `sources` field.
    referenced: set[str] = set()
    for sub in WIKI_SUBDIRS:
        d = wiki_root / sub
        if not d.is_dir():
            continue
        for p in d.glob("*.md"):
            for v in _frontmatter_sources(p.read_text(encoding="utf-8", errors="replace")):
                referenced.add(_norm(v))

    # A raw file is "touched" when its own project-relative path (or its
    # filename) appears in the referenced set — robust to the backslash /
    # raw-prefix variants the pipeline stored historically.
    def is_touched(p: Path) -> bool:
        rel = _norm(str(p.relative_to(root)))
        for ref in referenced:
            if ref == rel:
                return True
            if "/" in ref and ref.split("/")[-1] == p.name:
                return True
        return False

    backlog = [p for p in raw_files if not is_touched(p)]

    # Group by theme = first path segment under raw/ (e.g. "sources/01_新手入门").
    by_theme: dict[str, list[Path]] = defaultdict(list)
    for p in backlog:
        rel = p.relative_to(raw_root)
        parts = rel.parts
        theme = parts[0] if parts else "(root)"
        if len(parts) >= 2:
            theme = f"{parts[0]}/{parts[1]}"
        by_theme[theme].append(p)

    batches: list[dict] = []
    for theme in sorted(by_theme, key=lambda t: -len(by_theme[t])):
        files = by_theme[theme]
        for i in range(0, len(files), args.batch):
            chunk = files[i:i + args.batch]
            batches.append({
                "theme": theme,
                "batch_no": len(batches) + 1,
                "files": [p.relative_to(root).as_posix() for p in chunk],
            })

    touched = len(raw_files) - len(backlog)
    print(f"[backlog] raw ingestible files: {len(raw_files)}")
    print(f"[backlog] already referenced (touched): {touched}  (tap rate {touched/len(raw_files)*100:.1f}%)")
    print(f"[backlog] re-ingest backlog: {len(backlog)}")
    print(f"[backlog] batches (≤{args.batch}/batch): {len(batches)}")
    print("[backlog] by theme:")
    for theme in sorted(by_theme, key=lambda t: -len(by_theme[t])):
        print(f"  {theme:<24} {len(by_theme[theme])}")
    print(f"[backlog] first batch preview ({min(args.batch, len(batches[0]['files'])) if batches else 0} files):")
    if batches:
        for f in batches[0]["files"][:5]:
            print(f"  - {f}")

    if args.out:
        out = Path(args.out)
        out.write_text(json.dumps({
            "summary": {
                "raw_total": len(raw_files),
                "touched": touched,
                "backlog": len(backlog),
                "batches": len(batches),
                "batch_size": args.batch,
            },
            "batches": batches,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[backlog] manifest written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
