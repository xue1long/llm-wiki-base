"""H4 repair driver: rename 4 novel-wiki pages whose ids carry CJK
punctuation (illegal under the H4 id charset).

wiki-repair-novel-wiki H4: ids must match
    ^(?:card_[0-9a-f]{13}_[0-9a-f]{8}_[a-z0-9-一-鿿]+|[a-z0-9-一-鿿]+)$
The 4 offenders embedded `、` / `（` / `）` / `，` between dashes. The
repair drops the punctuation (title-minus-punctuation = new id), rewrites
every in-corpus reference to the old id (body ``[[type/old]]`` wikilinks,
frontmatter ``relations[].target``, index.md row, own ``id:`` line), then
``git mv`` each file to the new id.

Old ids never occur inside titles or prose — only as page references —
so a corpus-wide exact-string replace of ``old_id -> new_id`` is safe.

Usage:
    python scripts/apply_h4_renames.py [--apply] [--wiki PATH] [--out PATH]

    default = dry-run (reports occurrences + git mv plan, no writes)
    --apply = perform the replacements and git mv
"""
from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WIKI = REPO_ROOT / "knowledge" / "novel-wiki" / "wiki"
DEFAULT_QUALITY_DIR = REPO_ROOT / "knowledge" / "novel-wiki" / ".index" / "quality"

# (old_id, new_id, type_dir, display_title) — new id = title minus CJK punct
RENAMES: list[tuple[str, str, str, str]] = [
    ("语言-、-动作-、-神态结合描写", "语言动作神态结合描写", "concepts", "语言、动作、神态结合描写"),
    ("语言描写-（-对话描写-）", "语言描写对话描写", "concepts", "语言描写（对话描写）"),
    ("我的妈妈-（-课文片段-）", "我的妈妈课文片段", "entities", "我的妈妈（课文片段）"),
    ("走一步-，-再走一步", "走一步再走一步", "entities", "走一步，再走一步"),
]


def _iter_md(wiki_root: Path):
    for md in sorted(wiki_root.rglob("*.md")):
        rel = md.relative_to(wiki_root)
        if len(rel.parts) == 1 and rel.name in {"index.md", "log.md"}:
            yield md, rel
        elif len(rel.parts) >= 2 and rel.parts[0] in {
            "concepts", "sources", "entities", "synthesis", "_stubs",
        }:
            yield md, rel


def _read_preserve(path: Path) -> str:
    """Read text with newline='' so CRLF/LF line endings survive untouched."""
    with open(path, "r", encoding="utf-8", newline="") as f:
        return f.read()


def _write_preserve(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def _git(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--apply", action="store_true", help="perform replacements + git mv")
    parser.add_argument("--wiki", type=Path, default=DEFAULT_WIKI)
    parser.add_argument("--out", type=Path,
                        help="audit JSON path (default .index/quality/fix-h4-renames-<ts>.json)")
    args = parser.parse_args(argv)

    wiki_root = Path(args.wiki).resolve()
    if not wiki_root.is_dir():
        print(f"error: not a directory: {wiki_root}", file=sys.stderr)
        return 2

    # Existing ids to guard against collisions.
    existing: set[str] = set()
    for md, _rel in _iter_md(wiki_root):
        text = _read_preserve(md)
        if text.startswith("﻿"):
            text = text[1:]
        if not text.startswith("---\n"):
            continue
        end = text.find("\n---", 4)
        for line in text[4:end if end >= 0 else None].split("\n"):
            if line.startswith("id:"):
                pid = line[3:].strip()
                if pid:
                    existing.add(pid)
                break
    for _old, new, _typ, _t in RENAMES:
        if new in existing:
            print(f"error: target id already exists: {new}", file=sys.stderr)
            return 2

    # occurrence scan + optional replace per (old -> new)
    changed: list[dict] = []
    for old, new, typ, title in RENAMES:
        hits: list[dict] = []
        for md, rel in _iter_md(wiki_root):
            text = _read_preserve(md)
            n = text.count(old)
            if n:
                hits.append({"file": str(rel), "occurrences": n})
                if args.apply:
                    _write_preserve(md, text.replace(old, new))
        # move the page file(s) with matching old filename stem
        moved: list[str] = []
        if args.apply:
            src = wiki_root / typ / f"{old}.md"
            dst = wiki_root / typ / f"{new}.md"
            if src.exists():
                r = _git(["mv", str(src.relative_to(REPO_ROOT)), str(dst.relative_to(REPO_ROOT))])
                if r.returncode != 0:
                    print(f"git mv failed for {old}: {r.stderr}", file=sys.stderr)
                    return 2
                moved.append(str(dst.relative_to(REPO_ROOT)))
        changed.append({
            "old_id": old, "new_id": new, "type": typ, "title": title,
            "hits": hits, "moved": moved,
        })

    report = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "wiki_root": str(wiki_root),
        "applied": args.apply,
        "renames": changed,
    }
    out = (args.out or DEFAULT_QUALITY_DIR / f"fix-h4-renames-{datetime.datetime.now():%Y%m%d-%H%M%S}.json").resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Audit: {out}")
    if not args.apply:
        print("(dry-run; pass --apply to perform replacements + git mv)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
