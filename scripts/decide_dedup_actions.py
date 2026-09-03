"""Recommend dedup action for each duplicate-title group.

wiki-repair-novel-wiki §6: each group gets one of:
  - merge        (combine content; only one survives as canonical)
  - supersede    (one page replaces the others; others become _stubs)
  - alias        (one stays as canonical; others redirect via SlugAliasRegistry)
  - disambiguate (titles need renaming; each page is genuinely distinct)

This script CLASSIFIES based on observable signals (page-type split,
size diff, content overlap heuristics) and emits a decisions JSON.
It does NOT mutate any page or alias state — all destructive changes
require human approval via the report.

Usage:
    python scripts/decide_dedup_actions.py [--quality-dir PATH]
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_QUALITY_DIR = REPO_ROOT / "knowledge" / "novel-wiki" / ".index" / "quality"
WIKI_ROOT = REPO_ROOT / "knowledge" / "novel-wiki" / "wiki"


def _read_first_paragraph(path: Path, max_chars: int = 200) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if text.startswith("﻿"):
        text = text[1:]
    end = text.find("\n---", 4)
    body = text[end + 4:].lstrip("\n") if end >= 0 else text
    body = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL).strip()
    return body[:max_chars]


def _body_size(path: Path) -> int:
    try:
        return len(path.read_bytes())
    except OSError:
        return 0


def _type_from_path(p: Path) -> str | None:
    try:
        return p.relative_to(WIKI_ROOT).parts[0]
    except (ValueError, IndexError):
        return None


def classify_group(group: dict) -> dict:
    """Apply rules to recommend an action per group."""
    pages = group["pages"]
    title = group["title"]

    # Annotate each page
    enriched = []
    for p in pages:
        path = WIKI_ROOT / p["path"]
        body = _read_first_paragraph(path)
        size = _body_size(path)
        ptype = _type_from_path(path)
        enriched.append({
            **p,
            "absolute_path": str(path),
            "page_type": ptype,
            "body_size": size,
            "first_paragraph": body,
        })

    # Sort: largest body first (likely most informative)
    enriched.sort(key=lambda x: -x["body_size"])

    types = [p["page_type"] for p in enriched]
    ids = [p["id"] for p in enriched]

    # Rule A: same id, different page types (concepts vs entities)
    # → ALIAS the entity to the concept (concept type is richer)
    if len(set(ids)) == 1 and len(set(types)) > 1:
        canonical = next((p for p in enriched if p["page_type"] == "concepts"), enriched[0])
        aliases = [p for p in enriched if p["id"] != canonical["id"] or p["absolute_path"] != canonical["absolute_path"]]
        return {
            "title": title,
            "count": len(enriched),
            "rule": "same-id-different-type",
            "recommended_action": "alias",
            "rationale": "Same id but different page-type folders; canonical lives in concepts (richer type), entity pages become aliases.",
            "canonical": {"id": canonical["id"], "path": canonical["path"], "type": canonical["page_type"], "size": canonical["body_size"]},
            "aliases_to_register": [
                {"id": a["id"], "path": a["path"], "type": a["page_type"], "size": a["body_size"]}
                for a in enriched if a["absolute_path"] != canonical["absolute_path"]
            ],
            "pages": enriched,
        }

    # Rule B: multiple card-id suffixed variants of one title
    # (typical of repeated ingestion runs) → SUPERSEDE, keep largest
    if all(re.search(r"-[0-9a-f]{8}", p["id"]) for p in enriched):
        canonical = enriched[0]  # largest body
        superseded = enriched[1:]
        return {
            "title": title,
            "count": len(enriched),
            "rule": "card-id-suffix-collision",
            "recommended_action": "supersede",
            "rationale": "Repeated ingestion created card-id variants of same title; supersede smaller with the largest body.",
            "canonical": {"id": canonical["id"], "path": canonical["path"], "type": canonical["page_type"], "size": canonical["body_size"]},
            "superseded": [
                {"id": s["id"], "path": s["path"], "type": s["page_type"], "size": s["body_size"]}
                for s in superseded
            ],
            "pages": enriched,
        }

    # Default: defer to human
    return {
        "title": title,
        "count": len(enriched),
        "rule": "manual-review",
        "recommended_action": "disambiguate",
        "rationale": "Patterns don't match an automated rule; defer to human reviewer to rename or merge.",
        "canonical": None,
        "pages": enriched,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--quality-dir", type=Path, default=DEFAULT_QUALITY_DIR)
    args = parser.parse_args(argv)

    qd = args.quality_dir
    src_path = sorted(qd.glob("duplicate-titles-*.json"))
    if not src_path:
        print("error: duplicate-titles-*.json not found", file=sys.stderr)
        return 1
    src = json.loads(src_path[-1].read_text(encoding="utf-8", errors="replace"))

    decisions = []
    counts: dict[str, int] = {}
    for group in src["groups"]:
        d = classify_group(group)
        decisions.append(d)
        counts[d["recommended_action"]] = counts.get(d["recommended_action"], 0) + 1

    out = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "wiki_root": str(WIKI_ROOT),
        "source_report": str(src_path[-1]),
        "summary": {
            "total_groups": src["total_duplicate_groups"],
            "total_pages": src["total_duplicate_pages"],
            "by_action": counts,
        },
        "decisions": decisions,
        "operator_notes": (
            "alias    — register aliases via src.wiki.features.slug_aliases.SlugAliasRegistry; "
            "no page content changes.\n"
            "supersede— move smaller pages to wiki/_stubs/<id>.md and add a 'superseded_by: <canonical_id>' "
            "frontmatter field; preserves history.\n"
            "disambiguate — rename one or both pages' titles to differentiate; "
            "manual review required to choose non-ambiguous titles.\n"
            "merge    — manually combine body content; the chosen canonical absorbs the other."
        ),
    }

    today = datetime.datetime.now().strftime("%Y%m%d")
    out_path = qd / f"dedup-decisions-{today}.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Groups: {out['summary']['total_groups']}  pages: {out['summary']['total_pages']}")
    print(f"Actions: {out['summary']['by_action']}")
    print(f"Report:  {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))