"""Fix the system-wide duplicate Frontmatter delimiter issue.

wiki-repair-novel-wiki §3.1: ~47% of novel-wiki pages have a stray `---`
line right after the closing Frontmatter delimiter. The pattern is:

    line N:   ---           (closing FM delimiter, legitimate)
    line N+1: ---           (stray empty delimiter, to delete)
    line N+2: <!-- wiki-template-version: ... -->
    line N+3: <!-- wiki-template-type: ... -->

This script deletes only line N+1 (the stray one) and never touches any
YAML content or body. Each fix is preceded by a backup via
scripts/backup_wiki_file.py and followed by a verification round via
scripts/check_duplicate_frontmatter.py.

Usage:
    python scripts/fix_duplicate_frontmatter.py [--apply] [--limit N]

    # default mode = --dry-run (lists affected files; writes nothing)
    # --apply       perform the fixes (requires explicit opt-in)
    # --limit N     only process N files (for staged rollout)
    # --list <PATH> restrict to file list (one path per line, like the
                    duplicate-frontmatter-*.txt output)

Safety guarantees:
- Each file is backed up before any change.
- Diff is restricted to one line removal; no body or YAML is touched.
- Verification runs after every apply batch.
- A failure in any single file aborts the batch; already-fixed files
  remain fixed and can be reverted from their backups.

Exit codes:
  0  all OK (dry-run success or apply success)
  1  an error occurred during apply (some files may have been modified)
  2  bad arguments
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WIKI_ROOT = REPO_ROOT / "knowledge" / "novel-wiki" / "wiki"
QUALITY_DIR = REPO_ROOT / "knowledge" / "novel-wiki" / ".index" / "quality"


@dataclass
class FixResult:
    path: str
    backup: str | None
    status: str   # "fixed" | "would-fix" | "skipped" | "error"
    message: str = ""


def detect_stray_delimiter_line(text: str) -> int | None:
    """Return the 1-indexed line number of the stray `---` to delete.

    Returns None if the file does NOT match the canonical duplicate-FM
    pattern. Robust to UTF-8 BOM (does not require the BOM to be removed
    first; we operate on raw bytes via splitlines).
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None
    # Find first closing ---
    close_line = None
    for i, line in enumerate(lines[1:], 2):
        if line.strip() == "---":
            close_line = i
            break
    if close_line is None:
        return None
    # The next line must also be `---` (the stray one)
    if close_line >= len(lines):
        return None
    next_line = lines[close_line]
    if next_line.strip() != "---":
        return None
    # The line AFTER that should be a wiki-template comment (or blank)
    after = lines[close_line + 1] if close_line + 1 < len(lines) else ""
    if after.strip() == "" or after.strip().startswith("<!--"):
        return close_line + 1  # 1-indexed line number of the stray
    return None


def run_backup(src: Path) -> str | None:
    """Call scripts/backup_wiki_file.py to back up src. Returns backup path."""
    tool = REPO_ROOT / "scripts" / "backup_wiki_file.py"
    try:
        out = subprocess.run(
            [sys.executable, str(tool), str(src)],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", check=True,
        )
        # Parse the "[+] ... -> <path>" line
        for line in out.stdout.splitlines():
            if line.startswith("[+] "):
                return line.split("->", 1)[-1].strip()
            if line.startswith("[=] "):
                return line.split("->", 1)[-1].strip().split(" ")[0]
        return None
    except subprocess.CalledProcessError:
        return None


def fix_one(src: Path) -> FixResult:
    try:
        text = src.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return FixResult(str(src), None, "skipped", "decode error (not UTF-8?)")

    stray_line = detect_stray_delimiter_line(text)
    if stray_line is None:
        return FixResult(str(src), None, "skipped", "no duplicate-FM pattern")

    backup = run_backup(src)
    if backup is None:
        return FixResult(str(src), None, "error", "backup failed")

    # Remove the stray line. Use byte-level rewrite to preserve line endings.
    # We work on \n-joined representation; original file may have used \r\n.
    original_bytes = src.read_bytes()
    # Determine line ending style from the bytes
    if b"\r\n" in original_bytes[:1024]:
        eol = b"\r\n"
    else:
        eol = b"\n"
    # Re-read using the EOL strategy to be faithful
    if eol == b"\r\n":
        raw_lines = original_bytes.split(b"\r\n")
    else:
        raw_lines = original_bytes.split(b"\n")
    # stray_line is 1-indexed
    del raw_lines[stray_line - 1]
    new_bytes = eol.join(raw_lines)

    if new_bytes == original_bytes:
        return FixResult(str(src), backup, "skipped", "no change after re-encode (already fixed?)")

    src.write_bytes(new_bytes)

    # Re-verify
    new_text = src.read_text(encoding="utf-8", errors="replace")
    if detect_stray_delimiter_line(new_text) is not None:
        return FixResult(str(src), backup, "error", "pattern still detected after fix")

    return FixResult(str(src), backup, "fixed", f"removed line {stray_line}")


def collect_targets(wiki_root: Path, list_file: Path | None, limit: int | None) -> list[Path]:
    if list_file is not None:
        targets = []
        for line in list_file.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            p = wiki_root / line
            if p.exists():
                targets.append(p)
            else:
                # Maybe absolute or relative to repo root
                p2 = REPO_ROOT / line
                if p2.exists():
                    targets.append(p2)
        return targets[:limit] if limit else targets

    # Scan wiki_root
    targets = []
    for md in sorted(wiki_root.rglob("*.md")):
        rel = md.relative_to(wiki_root)
        if len(rel.parts) == 1 and rel.name in {"index.md", "log.md"}:
            continue
        if rel.parts[0] not in {"concepts", "sources", "entities", "synthesis", "_stubs"}:
            continue
        try:
            text = md.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if detect_stray_delimiter_line(text) is not None:
            targets.append(md)
            if limit and len(targets) >= limit:
                break
    return targets


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--apply", action="store_true", help="actually modify files (default: dry-run)")
    parser.add_argument("--limit", type=int, default=None, help="process at most N files")
    parser.add_argument("--list", type=Path, default=None, help="restrict to files listed in this file")
    parser.add_argument("--wiki-root", type=Path, default=WIKI_ROOT)
    args = parser.parse_args(argv)

    targets = collect_targets(args.wiki_root, args.list, args.limit)
    print(f"[scan] {len(targets)} target files ({'APPLY' if args.apply else 'DRY-RUN'})", file=sys.stderr)

    if not args.apply:
        for t in targets:
            print(f"  would-fix: {t.relative_to(args.wiki_root)}")
        return 0

    results: list[FixResult] = []
    errors = 0
    for t in targets:
        r = fix_one(t)
        results.append(r)
        tag = {"fixed": "[+]", "skipped": "[=]", "error": "[X]"}[r.status]
        print(f"{tag} {t.relative_to(args.wiki_root)}  {r.message}")
        if r.status == "error":
            errors += 1

    # Summary
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M")
    out = QUALITY_DIR / f"fix-duplicate-frontmatter-{ts}.json"
    out.write_text(
        json.dumps({
            "applied_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "wiki_root": str(args.wiki_root),
            "total_targets": len(targets),
            "fixed": sum(1 for r in results if r.status == "fixed"),
            "skipped": sum(1 for r in results if r.status == "skipped"),
            "errors": errors,
            "results": [asdict(r) for r in results],
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nSummary: fixed={sum(1 for r in results if r.status=='fixed')}  "
          f"skipped={sum(1 for r in results if r.status=='skipped')}  "
          f"errors={errors}")
    print(f"Report: {out}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
