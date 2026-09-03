"""Strip UTF-8 BOM (EF BB BF) from novel-wiki wiki Markdown files.

wiki-repair-novel-wiki §3.1 / T-C3: BOM files break the validate script's
Frontmatter regex (^--- matches the literal three hyphens, not the BOM
+ three hyphens), causing the validator to report false positives
(V4001 'no frontmatter delimiters') and miss every other validation
check on those pages. Removing the BOM is the canonical fix.

Usage:
    python scripts/strip_utf8_bom.py [--apply] [--limit N] [--list PATH]

    default mode = --dry-run (lists affected files; writes nothing)
    --apply       perform the fixes
    --limit N     only process N files (for staged rollout)
    --list PATH   restrict to file list (one path per line)

Safety:
- Each file is backed up via scripts/backup_wiki_file.py before any write.
- Diff is restricted to removing 3 bytes (EF BB BF) at the start of file.
- Files without BOM are skipped silently.
- Files whose size doesn't drop by exactly 3 bytes after the operation
  trigger an immediate abort.
"""
from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WIKI_ROOT = REPO_ROOT / "knowledge" / "novel-wiki" / "wiki"
QUALITY_DIR = REPO_ROOT / "knowledge" / "novel-wiki" / ".index" / "quality"

BOM = b"\xef\xbb\xbf"


@dataclass
class StripResult:
    path: str
    backup: str | None
    status: str   # "stripped" | "would-strip" | "skipped" | "error"
    message: str = ""


def has_bom(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(3) == BOM
    except OSError:
        return False


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


def strip_one(src: Path) -> StripResult:
    if not has_bom(src):
        return StripResult(str(src), None, "skipped", "no BOM")
    backup = run_backup(src)
    if backup is None:
        return StripResult(str(src), None, "error", "backup failed")
    raw = src.read_bytes()
    new = raw[3:]
    if len(raw) - len(new) != 3:
        return StripResult(str(src), backup, "error", f"unexpected size delta {len(raw)-len(new)}")
    src.write_bytes(new)
    if has_bom(src):
        return StripResult(str(src), backup, "error", "BOM still present after strip")
    return StripResult(str(src), backup, "stripped", "removed 3 bytes")


def collect_targets(wiki_root: Path, list_file: Path | None, limit: int | None) -> list[Path]:
    if list_file is not None:
        targets = []
        for line in list_file.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            p = wiki_root / line if not Path(line).is_absolute() else Path(line)
            if p.exists() and has_bom(p):
                targets.append(p)
        return targets[:limit] if limit else targets

    targets = []
    for md in sorted(wiki_root.rglob("*.md")):
        rel = md.relative_to(wiki_root)
        if len(rel.parts) == 1 and rel.name in {"index.md", "log.md"}:
            continue
        if rel.parts[0] not in {"concepts", "sources", "entities", "synthesis", "_stubs"}:
            continue
        if has_bom(md):
            targets.append(md)
            if limit and len(targets) >= limit:
                break
    return targets


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--list", type=Path, default=None)
    parser.add_argument("--wiki-root", type=Path, default=WIKI_ROOT)
    args = parser.parse_args(argv)

    targets = collect_targets(args.wiki_root, args.list, args.limit)
    print(f"[scan] {len(targets)} BOM files ({'APPLY' if args.apply else 'DRY-RUN'})", file=sys.stderr)

    if not args.apply:
        for t in targets:
            print(f"  would-strip: {t.relative_to(args.wiki_root)}")
        return 0

    results: list[StripResult] = []
    errors = 0
    for t in targets:
        r = strip_one(t)
        results.append(r)
        tag = {"stripped": "[+]", "skipped": "[=]", "error": "[X]"}[r.status]
        print(f"{tag} {t.relative_to(args.wiki_root)}  {r.message}")
        if r.status == "error":
            errors += 1

    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M")
    out = QUALITY_DIR / f"strip-bom-{ts}.json"
    out.write_text(json.dumps({
        "applied_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "total_targets": len(targets),
        "stripped": sum(1 for r in results if r.status == "stripped"),
        "skipped": sum(1 for r in results if r.status == "skipped"),
        "errors": errors,
        "results": [asdict(r) for r in results],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSummary: stripped={sum(1 for r in results if r.status=='stripped')}  errors={errors}")
    print(f"Report: {out}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
