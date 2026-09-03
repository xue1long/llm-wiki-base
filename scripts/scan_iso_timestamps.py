"""Scan novel-wiki for ISO-string timestamps in created_at / updated_at.

wiki-repair-novel-wiki §3.2: V4 schema requires Unix ms integer
timestamps. Pages with ISO date strings ('2026-08-10') are flagged.

Usage:
    python scripts/scan_iso_timestamps.py [<wiki_root>] [--out PATH]

    # default wiki_root = ./knowledge/novel-wiki/wiki

The script is read-only.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WIKI_ROOT = REPO_ROOT / "knowledge" / "novel-wiki" / "wiki"
DEFAULT_OUT = REPO_ROOT / "knowledge" / "novel-wiki" / ".index" / "quality"

# Match a Frontmatter key whose value is a quoted string (not a number)
ISO_STRING_RE = re.compile(
    r"^(created_at|updated_at):\s*['\"]([^'\"]+)['\"]\s*$",
    re.MULTILINE,
)


def _read_first_frontmatter(text: str) -> str | None:
    if text.startswith("﻿"):
        text = text[1:]
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end < 0:
        return None
    return text[4:end]


def scan(wiki_root: Path) -> list[dict]:
    flagged: list[dict] = []
    for md in sorted(wiki_root.rglob("*.md")):
        rel = md.relative_to(wiki_root)
        if len(rel.parts) == 1 and rel.name in {"index.md", "log.md"}:
            continue
        if rel.parts[0] not in {"concepts", "sources", "entities", "synthesis", "_stubs"}:
            continue
        try:
            text = md.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = md.read_bytes().decode("utf-8", errors="replace")
        fm_body = _read_first_frontmatter(text)
        if fm_body is None:
            continue
        for m in ISO_STRING_RE.finditer(fm_body):
            iso_str = m.group(2)
            try:
                # try parsing as ISO; convert to Unix ms
                dt = datetime.datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
                unix_ms = int(dt.timestamp() * 1000)
            except ValueError:
                unix_ms = None
            flagged.append({
                "path": str(rel).replace("\\", "/"),
                "field": m.group(1),
                "current_value": iso_str,
                "suggested_unix_ms": unix_ms,
                "convertible": unix_ms is not None,
            })
    return flagged


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("wiki_root", nargs="?", type=Path, default=DEFAULT_WIKI_ROOT)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.wiki_root.is_dir():
        print(f"error: {args.wiki_root} not a directory", file=sys.stderr)
        return 2

    findings = scan(args.wiki_root)
    summary = {
        "scanned_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "wiki_root": str(args.wiki_root),
        "total_iso_string_timestamps": len(findings),
        "convertible": sum(1 for f in findings if f["convertible"]),
        "unconvertible": sum(1 for f in findings if not f["convertible"]),
        "findings": findings,
    }
    out = args.out
    if out is None:
        ts = datetime.datetime.now().strftime("%Y%m%d")
        out = DEFAULT_OUT / f"iso-timestamps-{ts}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"ISO string timestamps: {len(findings)}  convertible: {summary['convertible']}")
    print(f"Written: {out}")
    for f in findings[:5]:
        ms = f["suggested_unix_ms"]
        print(f"  {f['path']} {f['field']}='{f['current_value']}' -> {ms}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
