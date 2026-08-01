"""build_reingest_backlog.py — Phase 4.1: raw files not yet referenced by any
wiki page's ``sources`` field, deduplicated and size-policed, grouped by theme
and batched ≤20 for re-ingest.

Read-only: never writes wiki data. With ``--out`` it writes a JSON batch
manifest a batch-runner can consume (a new file, not wiki state).

Size / dedup policy (2026-08-01 rewrite, Phase 4 audit H3.1/B7):
  - Content dedup: whitespace-compacted md5 fingerprint. Within a duplicate
    group one member is kept (prefer a batch-sized one); the rest are
    classified ``skipped(reason=duplicate_of)`` and never batched. Catches
    exact / whitespace-only dups (e.g. the cross-theme 东方玄幻/都市言情
    ``清朝有名得妃子`` pair). Header-line drift (下载时间/URL) is out of scope.
  - ``--tiny-chars`` (default 500): files with FEWER decoded characters are
    classified ``skipped(reason=tiny)`` — too thin to be worth a page.
  - ``--max-chars`` (default 8000, == generator.MAX_SOURCE_CHARS): files with
    MORE decoded characters are deferred to ``long_docs``. The generator
    truncates at 8000 chars, so ingesting a 1.6MB novel only extracts its
    opening — pointless. Long docs are NOT batched until a chunking
    capability lands.
  - Binary suffixes (pdf/docx/xlsx/epub) that the batch runner cannot
    ``read_text`` are classified ``skipped(reason=unhandled_format)``.

Manifest shape (consumers read only ``batches``):
  {
    "summary": {...},
    "batches": [{"theme", "batch_no", "files": [...]}],   # batch-sized, ingestible only
    "long_docs": [{"path", "chars"}],                     # deferred, out of batch scope
    "skipped": [{"path", "reason", "detail"}],            # duplicate_of | tiny | unhandled_format
  }
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

WIKI_SUBDIRS = ("sources", "entities", "concepts", "synthesis")
# Only files the ingest collector can actually process count toward the
# re-ingest backlog; skip obvious non-document artifacts.
INCLUDE_SUFFIXES = {".md", ".txt", ".pdf", ".docx", ".xlsx", ".html", ".htm", ".epub"}
# Suffixes the batch runner can pass to ``read_text`` without garbage output.
TEXT_SUFFIXES = {".md", ".txt", ".html", ".htm"}
BATCH_SIZE = 20
DEFAULT_MAX_CHARS = 8000   # == src/pipeline/generator.py MAX_SOURCE_CHARS
DEFAULT_TINY_CHARS = 500

_WS_RE = re.compile(r"\s+")


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


def _decode(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def _fingerprint(text: str) -> str:
    """Whitespace-compacted md5 — catches exact + whitespace-only dups."""
    return hashlib.md5(_WS_RE.sub("", text).encode("utf-8")).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(
        description="List unreferenced raw files, dedup + size-policy, group into ≤N-file batches.",
    )
    ap.add_argument("wiki_root", nargs="?", default="knowledge/novel-wiki",
                    help="project root (parent of raw/ and wiki/). default: knowledge/novel-wiki")
    ap.add_argument("--out", default=None,
                    help="write the batch manifest JSON to this path (default: stdout preview only)")
    ap.add_argument("--batch", type=int, default=BATCH_SIZE,
                    help=f"max files per batch (default {BATCH_SIZE})")
    ap.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS,
                    help=f"defer files LONGER than this many decoded chars to long_docs (default {DEFAULT_MAX_CHARS})")
    ap.add_argument("--tiny-chars", type=int, default=DEFAULT_TINY_CHARS,
                    help=f"skip files SHORTER than this many decoded chars (default {DEFAULT_TINY_CHARS})")
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

    candidates = [p for p in raw_files if not is_touched(p)]

    # --- classify binary suffixes before any decoding ---
    text_candidates = [p for p in candidates if p.suffix.lower() in TEXT_SUFFIXES]
    skipped: list[dict] = [
        {
            "path": p.relative_to(root).as_posix(),
            "reason": "unhandled_format",
            "detail": p.suffix.lower(),
        }
        for p in candidates
        if p.suffix.lower() not in TEXT_SUFFIXES
    ]

    # --- content fingerprint (decode once per file, cache) ---
    text_cache: dict[Path, str] = {}

    def get_text(p: Path) -> str:
        if p not in text_cache:
            text_cache[p] = _decode(p)
        return text_cache[p]

    def get_chars(p: Path) -> int:
        return len(get_text(p))

    def in_batch_range(p: Path) -> bool:
        n = get_chars(p)
        return n >= args.tiny_chars and n <= args.max_chars

    groups: dict[str, list[Path]] = defaultdict(list)
    for p in text_candidates:
        groups[_fingerprint(get_text(p))].append(p)

    # --- pick one keeper per dup group (prefer a batch-sized member) ---
    keepers: list[Path] = []
    for g in groups.values():
        g_sorted = sorted(g, key=lambda p: str(p))
        if len(g_sorted) == 1:
            keepers.append(g_sorted[0])
            continue
        in_range = [p for p in g_sorted if in_batch_range(p)]
        keeper = in_range[0] if in_range else g_sorted[0]
        keepers.append(keeper)
        for p in g_sorted:
            if p != keeper:
                skipped.append({
                    "path": p.relative_to(root).as_posix(),
                    "reason": "duplicate_of",
                    "detail": keeper.relative_to(root).as_posix(),
                })

    # --- size-policy classification of keepers ---
    ingestible: list[Path] = []
    long_docs: list[dict] = []
    tiny_count = 0
    for p in keepers:
        n = get_chars(p)
        if n < args.tiny_chars:
            tiny_count += 1
            skipped.append({
                "path": p.relative_to(root).as_posix(),
                "reason": "tiny",
                "detail": f"{n} chars",
            })
        elif n > args.max_chars:
            long_docs.append({
                "path": p.relative_to(root).as_posix(),
                "chars": n,
            })
        else:
            ingestible.append(p)

    # --- group ingestible files by theme and batch ---
    by_theme: dict[str, list[Path]] = defaultdict(list)
    for p in ingestible:
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

    n_dup = sum(1 for s in skipped if s["reason"] == "duplicate_of")
    n_unhandled = sum(1 for s in skipped if s["reason"] == "unhandled_format")
    summary = {
        "raw_total": len(raw_files),
        "touched": len(raw_files) - len(candidates),
        "backlog_candidates": len(candidates),
        "duplicate_groups": sum(1 for g in groups.values() if len(g) > 1),
        "skipped_duplicates": n_dup,
        "skipped_tiny": tiny_count,
        "skipped_unhandled_format": n_unhandled,
        "long_docs": len(long_docs),
        "ingestible": len(ingestible),
        "batches": len(batches),
        "batch_size": args.batch,
        "max_chars": args.max_chars,
        "tiny_chars": args.tiny_chars,
    }

    touched = len(raw_files) - len(candidates)
    print(f"[backlog] raw ingestible files: {len(raw_files)}")
    print(f"[backlog] already referenced (touched): {touched}  (tap rate {touched/len(raw_files)*100:.1f}%)")
    print(f"[backlog] re-ingest candidates: {len(candidates)}")
    print(f"[backlog]   -> ingestible (batched): {len(ingestible)}")
    print(f"[backlog]   -> long_docs (deferred >{args.max_chars} chars): {len(long_docs)}")
    print(f"[backlog]   -> skipped: duplicate_of={n_dup}, tiny={tiny_count}, unhandled_format={n_unhandled}")
    print(f"[backlog] batches (≤{args.batch}/batch): {len(batches)}")
    print("[backlog] by theme:")
    for theme in sorted(by_theme, key=lambda t: -len(by_theme[t])):
        print(f"  {theme:<24} {len(by_theme[theme])}")
    if long_docs:
        print("[backlog] top long_docs:")
        for d in sorted(long_docs, key=lambda d: -d["chars"])[:8]:
            print(f"  {d['chars']//1024}KB  {d['path']}")
    if batches:
        print(f"[backlog] first batch preview ({min(args.batch, len(batches[0]['files']))} files):")
        for f in batches[0]["files"][:5]:
            print(f"  - {f}")

    if args.out:
        out = Path(args.out)
        out.write_text(json.dumps({
            "summary": summary,
            "batches": batches,
            "long_docs": long_docs,
            "skipped": skipped,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[backlog] manifest written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
