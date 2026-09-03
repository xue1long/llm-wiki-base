"""Idempotent backup utility for wiki page fixes (wiki-repair-novel-wiki §10).

Creates timestamped backups of wiki Markdown files before any structural
edit. The default mode is idempotent: if a backup with the same timestamp
already exists and contains byte-identical content, the call is a no-op;
if it differs, a `-N` suffix is added (caller must investigate). Use
--strict to fail instead of appending.

Naming convention (Windows PowerShell friendly):
    <file>.bak.YYYYMMDD-HHMM            # default
    <file>.bak.YYYYMMDD                 # --date-only
    <file>.bak.YYYYMMDD-HHMM-2          # auto on collision

Usage:
    python scripts/backup_wiki_file.py <file> [<file> ...]
    python scripts/backup_wiki_file.py --date-only <file>
    python scripts/backup_wiki_file.py --strict <file>

    # JSON output (for piping into batch scripts):
    python scripts/backup_wiki_file.py --json <file> [<file> ...]

Exit codes:
    0  success (backups created or skipped as no-op)
    1  --strict mode and backup already differs
    2  source file does not exist
    3  source file is not under knowledge/<project>/wiki/ (safety check)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Allow only wiki/ trees under known project roots. Adjust here if more
# projects are added.
KNOWN_WIKI_ROOTS = (
    REPO_ROOT / "knowledge" / "novel-wiki" / "wiki",
)


@dataclass
class BackupResult:
    source: str
    backup: str | None
    status: str   # "created" | "no-op" | "collided-N" | "error"
    message: str = ""


def _is_under_known_wiki(path: Path) -> bool:
    """Refuse to backup files outside known wiki roots (defence in depth)."""
    try:
        path_resolved = path.resolve()
    except OSError:
        return False
    for root in KNOWN_WIKI_ROOTS:
        try:
            path_resolved.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def backup_one(
    src: Path,
    timestamp_format: str = "%Y%m%d-%H%M",
    strict: bool = False,
) -> BackupResult:
    if not src.exists():
        return BackupResult(str(src), None, "error", "source does not exist")
    if not _is_under_known_wiki(src):
        return BackupResult(
            str(src), None, "error",
            "source is not under a known wiki root (refusing to backup)",
        )

    suffix = src.suffix  # ".md"
    stem = src.name[: -len(suffix)] if suffix else src.name
    parent = src.parent
    timestamp = datetime.now().strftime(timestamp_format)
    candidate = parent / f"{stem}{suffix}.bak.{timestamp}"

    # Idempotency: if backup exists with identical bytes, no-op.
    if candidate.exists():
        if _digest(candidate) == _digest(src):
            return BackupResult(str(src), str(candidate), "no-op", "identical backup exists")
        if strict:
            return BackupResult(
                str(src), str(candidate), "error",
                "backup exists with different content (--strict refused)",
            )
        # Find next free -N suffix
        n = 2
        while True:
            cand_n = parent / f"{stem}{suffix}.bak.{timestamp}-{n}"
            if not cand_n.exists():
                candidate = cand_n
                break
            n += 1
            if n > 999:
                return BackupResult(
                    str(src), None, "error",
                    "could not allocate -N suffix (999 collisions)",
                )
        # Fall through to write the -N variant.

    # Atomic copy: read+write so a half-written backup never exists.
    data = src.read_bytes()
    candidate.write_bytes(data)
    return BackupResult(
        str(src), str(candidate),
        "collided-N" if (timestamp + "-2") in candidate.name else "created",
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("files", nargs="+", type=Path, help="files to backup")
    parser.add_argument(
        "--date-only", action="store_true",
        help="use YYYYMMDD (no time) instead of YYYYMMDD-HHMM",
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="fail if a backup with same timestamp already exists with different content",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON array of results")
    args = parser.parse_args(argv)

    ts_format = "%Y%m%d" if args.date_only else "%Y%m%d-%H%M"
    results = [backup_one(f, timestamp_format=ts_format, strict=args.strict) for f in args.files]

    if args.json:
        print(json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2))
    else:
        for r in results:
            tag = {
                "created": "[+]",
                "no-op": "[=]",
                "collided-N": "[!]",
                "error": "[X]",
            }[r.status]
            line = f"{tag} {r.source}"
            if r.backup:
                line += f" -> {r.backup}"
            if r.message:
                line += f"  ({r.message})"
            print(line)

    # Exit non-zero if any result is an error (under non-strict mode, errors
    # are limited to: source missing, source outside wiki, allocation failure).
    return 1 if any(r.status == "error" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
