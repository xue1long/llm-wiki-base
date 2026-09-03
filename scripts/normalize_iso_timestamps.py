"""Normalize ISO-string timestamps to Unix ms in novel-wiki pages.

wiki-repair-novel-wiki §3.2: V4 schema requires `created_at` and
`updated_at` to be Unix ms integers. Some pages still have ISO date
strings like '2026-08-10'. This script converts them in-place.

Usage:
    python scripts/normalize_iso_timestamps.py [--apply]

    default = --dry-run (lists affected files; writes nothing)
    --apply = actually modify files

Safety:
- Each file is backed up via scripts/backup_wiki_file.py.
- Only `created_at:` / `updated_at:` lines with a quoted string value
  are touched. Numeric values are left untouched.
- Files that already use Unix ms are skipped.
- Lines are matched precisely (anchored regex) to avoid touching
  unrelated YAML fields.
- Writes preserve byte-level layout (LF vs CRLF, line endings).
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

ISO_STRING_RE = re.compile(
    r"^(created_at|updated_at):\s*['\"]([^'\"]+)['\"]\s*$",
    re.MULTILINE,
)


@dataclass
class FixResult:
    path: str
    backup: str | None
    status: str   # "fixed" | "would-fix" | "skipped" | "error"
    changes: list[dict]
    message: str = ""


def iso_to_unix_ms(iso: str) -> int | None:
    try:
        dt = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return int(dt.timestamp() * 1000)
    except ValueError:
        return None


def first_frontmatter(text: str) -> str | None:
    if text.startswith("﻿"):
        text = text[1:]
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end < 0:
        return None
    return text[4:end]


def run_backup(src: Path) -> str | None:
    tool = REPO_ROOT / "scripts" / "backup_wiki_file.py"
    try:
        out = subprocess.run(
            [sys.executable, str(tool), str(src)],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", check=True,
        )
        for line in out.stdout.splitlines():
            if line.startswith("[+] ") or line.startswith("[=] "):
                return line.split("->", 1)[-1].strip().split("  (")[0].strip()
        return None
    except subprocess.CalledProcessError:
        return None


def fix_one(src: Path) -> FixResult:
    try:
        text = src.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return FixResult(str(src), None, "skipped", [], "decode error")
    fm_body = first_frontmatter(text)
    if fm_body is None:
        return FixResult(str(src), None, "skipped", [], "no first FM block")
    matches = list(ISO_STRING_RE.finditer(fm_body))
    if not matches:
        return FixResult(str(src), None, "skipped", [], "no ISO string timestamps")

    # Compute all conversions
    changes = []
    for m in matches:
        field, iso = m.group(1), m.group(2)
        unix_ms = iso_to_unix_ms(iso)
        if unix_ms is None:
            return FixResult(str(src), None, "skipped", changes, f"unparseable ISO: {iso}")
        changes.append({
            "field": field,
            "from": iso,
            "to": unix_ms,
            "match_text": m.group(0),
        })

    backup = run_backup(src)
    if backup is None:
        return FixResult(str(src), None, "error", changes, "backup failed")

    # Apply line-by-line to avoid cross-line mangling
    raw_bytes = src.read_bytes()
    if b"\r\n" in raw_bytes[:1024]:
        eol = b"\r\n"
        lines = raw_bytes.split(b"\r\n")
    else:
        eol = b"\n"
        lines = raw_bytes.split(b"\n")

    new_lines = []
    for line in lines:
        s = line.decode("utf-8")
        for ch in changes:
            if ch["match_text"] in s:
                s = s.replace(ch["match_text"], f'{ch["field"]}: {ch["to"]}')
        new_lines.append(s.encode("utf-8"))
    new_bytes = eol.join(new_lines)

    if new_bytes == raw_bytes:
        return FixResult(str(src), backup, "skipped", changes, "no change after rewrite")

    src.write_bytes(new_bytes)

    # Verify
    verify_text = src.read_text(encoding="utf-8")
    verify_fm = first_frontmatter(verify_text)
    if verify_fm is None:
        return FixResult(str(src), backup, "error", changes, "FM block lost after rewrite")
    for ch in changes:
        if f'{ch["field"]}: {ch["to"]}' not in verify_fm:
            return FixResult(str(src), backup, "error", changes, f"missing {ch['field']}={ch['to']} after rewrite")

    return FixResult(str(src), backup, "fixed", changes, f"converted {len(changes)} timestamps")


def collect_targets(wiki_root: Path) -> list[Path]:
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
        fm = first_frontmatter(text)
        if fm and ISO_STRING_RE.search(fm):
            targets.append(md)
    return targets


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--wiki-root", type=Path, default=WIKI_ROOT)
    args = parser.parse_args(argv)

    targets = collect_targets(args.wiki_root)
    print(f"[scan] {len(targets)} files with ISO string timestamps ({'APPLY' if args.apply else 'DRY-RUN'})", file=sys.stderr)

    if not args.apply:
        for t in targets[:10]:
            print(f"  would-fix: {t.relative_to(args.wiki_root)}")
        if len(targets) > 10:
            print(f"  ... and {len(targets) - 10} more")
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

    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M")
    out = QUALITY_DIR / f"fix-iso-timestamps-{ts}.json"
    out.write_text(json.dumps({
        "applied_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "total_targets": len(targets),
        "fixed": sum(1 for r in results if r.status == "fixed"),
        "skipped": sum(1 for r in results if r.status == "skipped"),
        "errors": errors,
        "results": [asdict(r) for r in results],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSummary: fixed={sum(1 for r in results if r.status=='fixed')}  errors={errors}")
    print(f"Report: {out}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
