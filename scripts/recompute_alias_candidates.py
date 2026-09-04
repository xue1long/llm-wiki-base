"""Recompute broken-link alias candidates from the LIVE corpus.

The H2 broken-link / dangling-relation JSON reports in
``knowledge/novel-wiki/.index/quality/`` are byte-corrupt (tens of
thousands of ``U+FFFD`` replacement chars) and unrecoverable, so
``scripts/derive_alias_candidates.py`` (which reads them) cannot produce
a trustworthy candidate list. This script instead recomputes the broken
target set directly from the corpus markdown (clean UTF-8):

1. Collect every live page id (frontmatter ``id:``) from the type dirs.
2. Scan frontmatter ``relations[].target`` and body ``[[wikilink]]``
   targets, stripping a known type-dir / namespace head (``concepts/``,
   ``sources/``, ``entities/``, ``synthesis/``, ``_stubs/``,
   ``credibility:…``, ``taxonomy:…``) to obtain the bare target.
3. Broken = bare target missing from the live id set. Namespaced
   (credibility/taxonomy) heads are excluded — they resolve differently.
4. Feed the clean broken set through the same heuristics as the original
   derive script, and additionally mark **surface variants** — candidates
   where alias and canonical are identical after dropping
   case/dash/CJK-punctuation — as the safe auto-registerable subset.

Output is a review report; no alias is registered here. Operators review
then register via ``SlugAliasRegistry``.

Usage:
    python scripts/recompute_alias_candidates.py [--wiki PATH] [--out PATH] [--apply]

    default = dry-run (writes the review JSON only)
    --apply = additionally register the recommended surface-variant set
              (identical modulo case/dash/CJK-punctuation) via
              SlugAliasRegistry, after backing up any existing registry
              file. Truncation/substring guesses are never auto-registered.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROJECT = REPO_ROOT / "knowledge" / "novel-wiki"
DEFAULT_WIKI = DEFAULT_PROJECT / "wiki"
DEFAULT_QUALITY_DIR = DEFAULT_PROJECT / ".index" / "quality"
TYPE_DIRS = {"concepts", "sources", "entities", "synthesis", "_stubs"}
WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")
CJK_RANGE = r"一-鿿"
_H4_MAPPINGS = [
    # Phase A renames: old id -> new id (future LLM re-emission fallback)
    ("语言-、-动作-、-神态结合描写", "语言动作神态结合描写"),
    ("语言描写-（-对话描写-）", "语言描写对话描写"),
    ("我的妈妈-（-课文片段-）", "我的妈妈课文片段"),
    ("走一步-，-再走一步", "走一步再走一步"),
]


def _normalize(slug: str) -> str:
    """Drop every non-alphanumeric char (dashes, CJK punct, case) for
    surface-form comparison."""
    return re.sub(r"[^a-z0-9" + CJK_RANGE + r"]", "", slug.lower())


def _is_surface_variant(alias: str, canonical: str) -> bool:
    """alias and canonical are the same slug modulo case / dashes /
    CJK punctuation — a safe, unambiguous alias registration."""
    return alias != canonical and _normalize(alias) == _normalize(canonical)


def _iter_md(wiki_root: Path):
    for md in sorted(wiki_root.rglob("*.md")):
        rel = md.relative_to(wiki_root)
        if len(rel.parts) == 1 and rel.name in {"index.md", "log.md"}:
            continue
        if rel.parts[0] not in TYPE_DIRS:
            continue
        yield md, rel


def _read_preserve(path: Path) -> str:
    with open(path, "r", encoding="utf-8", newline="") as f:
        return f.read()


def recompute(wiki_root: Path) -> dict:
    """Return {existing_ids, targets, broken: {bare: [refs]}} from live corpus."""
    existing: set[str] = set()
    refs: list[tuple[str, str, str]] = []  # (kind, src_rel, raw_target)

    for md, rel in _iter_md(wiki_root):
        text = _read_preserve(md)
        if text.startswith("﻿"):
            text = text[1:]
        if not text.startswith("---\n"):
            continue
        end = text.find("\n---", 4)
        if end < 0:
            continue
        fm = text[4:end]
        body = text[end + 4:]
        if body.startswith("\n"):
            body = body[1:]
        pid = None
        for line in fm.split("\n"):
            if line.startswith("id:"):
                pid = line[3:].strip()
                break
        if pid:
            existing.add(pid)
        for line in fm.split("\n"):
            s = line.strip()
            if s.startswith("target:"):
                refs.append(("relation", str(rel), s[7:].strip()))
        for m in WIKILINK_RE.finditer(body):
            refs.append(("wikilink", str(rel), m.group(1).strip()))

    def bare(target: str) -> tuple[str | None, str]:
        if "/" in target:
            head, _, rest = target.partition("/")
            if head in TYPE_DIRS or head.startswith("credibility") or head.startswith("taxonomy"):
                return head, rest
        return None, target

    broken: dict[str, list[dict]] = {}
    total = {"wikilink": 0, "relation": 0}
    for kind, src, raw in refs:
        total[kind] += 1
        head, b = bare(raw)
        if head and (head.startswith("credibility") or head.startswith("taxonomy")):
            continue  # namespaced refs — different resolution path
        if b in existing:
            continue
        broken.setdefault(b, []).append({"kind": kind, "src": src, "raw": raw})

    return {"existing_ids": sorted(existing), "total_refs": total, "broken": broken}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--wiki", type=Path, default=DEFAULT_WIKI)
    parser.add_argument("--out", type=Path,
                        help="report path (default .index/quality/alias-candidates-<date>-clean.json)")
    parser.add_argument("--apply", action="store_true",
                        help="register the recommended surface-variant set (after backup)")
    args = parser.parse_args(argv)

    wiki_root = Path(args.wiki).resolve()
    if not wiki_root.is_dir():
        print(f"error: not a directory: {wiki_root}", file=sys.stderr)
        return 2

    # Import the original derive heuristics (pure functions; live-corpus ids).
    sys.path.insert(0, str(REPO_ROOT))
    from scripts.derive_alias_candidates import _all_existing_ids, derive_candidates

    data = recompute(wiki_root)
    broken_targets = sorted(data["broken"])
    existing_ids = _all_existing_ids()

    cands = derive_candidates(broken_targets, existing_ids)
    surface = [c for c in cands if _is_surface_variant(c["alias"], c["canonical"])]
    other = [c for c in cands if not _is_surface_variant(c["alias"], c["canonical"])]

    # Recommended auto-register set = surface variants + H4 id fallbacks
    # (H4 mappings are themselves surface variants — punct/case only).
    recommended: list[dict] = [
        {"alias": c["alias"], "canonical": c["canonical"],
         "heuristic": c["heuristic"], "confidence": c["confidence"]}
        for c in surface
    ] + [
        {"alias": a, "canonical": c, "source": "phase-A-h4-rename"}
        for a, c in _H4_MAPPINGS
    ]

    report = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "wiki_root": str(wiki_root),
        "note": "Recomputed from live corpus; the H2 JSON reports are byte-corrupt and not used.",
        "existing_ids": len(existing_ids),
        "total_refs": data["total_refs"],
        "unique_broken_bare_targets": len(broken_targets),
        "candidate_total": len(cands),
        "recommend_surface_variant": {
            "count": len(recommended),
            "entries": recommended,
        },
        "candidates_for_human_review": [
            {"alias": c["alias"], "canonical": c["canonical"],
             "heuristic": c["heuristic"], "confidence": c["confidence"]}
            for c in other
        ],
        "broken_bare_targets": [
            {"target": t, "occurrences": len(v)}
            for t, v in sorted(data["broken"].items())
        ],
    }

    out = (args.out or DEFAULT_QUALITY_DIR / "alias-candidates-20260904-clean.json").resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(report, ensure_ascii=False, indent=2)
    assert "�" not in raw, "report must be clean UTF-8 (no U+FFFD)"
    out.write_text(raw, encoding="utf-8")
    print(f"Report: {out}")
    print(f"existing={len(existing_ids)} broken={len(broken_targets)} "
          f"candidates={len(cands)} surface_recommended={len(recommended)} "
          f"human_review={len(other)}")

    if args.apply:
        sys.path.insert(0, str(REPO_ROOT))
        from src.wiki.features.slug_aliases import SlugAliasRegistry

        project_root = DEFAULT_PROJECT if wiki_root == DEFAULT_WIKI.resolve() \
            else wiki_root.parent  # <project>/wiki -> <project>
        reg = SlugAliasRegistry(str(project_root))
        if reg._alias_path.exists():
            bak = reg._alias_path.with_suffix(
                ".json.bak." + datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
            shutil.copy2(reg._alias_path, bak)
            print(f"Registry backup: {bak}")
        reg.add_many((e["alias"], e["canonical"]) for e in recommended)
        reg.save()
        print(f"Registered {len(recommended)} surface-variant aliases -> "
              f"{reg._alias_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
