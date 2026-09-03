"""Derive slug alias candidates from H2 broken-link baseline.

wiki-repair-novel-wiki §4.2: heuristics over the existing broken-link
data to find high-confidence alias mappings. Output is a review list,
NOT an applied change — operators register aliases via
src.wiki.features.slug_aliases.SlugAliasRegistry after review.

Heuristics (in priority order):
1. **Stripped prefix**: a broken target like `1增强文章悬念之画外音第-1-段-94ef8ce7`
   is the canonical `1增强文章悬念之画外音第1段-94ef8ce7` with extra
   dash noise. Strip dashes inside CJK segments.
2. **Longest-prefix**: a broken target is exactly a kebab-prefix of
   one existing slug with no other candidate matching that prefix.
3. **Unique substring**: the broken target's normalized form appears
   as a substring of exactly one existing slug.

All candidates get a confidence score (HIGH/MEDIUM/LOW). HIGH
candidates are auto-applicable; MEDIUM/LOW require human review.

Usage:
    python scripts/derive_alias_candidates.py [--quality-dir PATH] [--apply]

    default = dry-run (writes JSON report, no alias mutation)
    --apply = also calls SlugAliasRegistry.add() for HIGH-confidence
              candidates only (after backing up the registry file)
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_QUALITY_DIR = REPO_ROOT / "knowledge" / "novel-wiki" / ".index" / "quality"
PROJECT_ROOT = REPO_ROOT / "knowledge" / "novel-wiki"

CJK_RANGE = r"一-鿿"


def _all_existing_ids() -> set[str]:
    """Collect every page id from wiki/<dir>/*.md frontmatter."""
    ids: set[str] = set()
    wiki_root = PROJECT_ROOT / "wiki"
    for md in wiki_root.rglob("*.md"):
        rel = md.relative_to(wiki_root)
        if len(rel.parts) == 1 and rel.name in {"index.md", "log.md"}:
            continue
        if rel.parts[0] not in {"concepts", "sources", "entities", "synthesis", "_stubs"}:
            continue
        try:
            text = md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # id: <value> at start of FM
        if text.startswith("﻿"):
            text = text[1:]
        if not text.startswith("---\n"):
            continue
        end = text.find("\n---", 4)
        if end < 0:
            continue
        for line in text[4:end].split("\n"):
            if line.startswith("id:"):
                pid = line[3:].strip()
                if pid:
                    ids.add(pid)
                break
    return ids


def _strip_dash_noise(slug: str) -> str:
    """Remove '-' that immediately follows a CJK char or precedes a digit
    sequence inside a CJK segment. Used for heuristic 1.
    """
    # Remove dash between CJK and digit, or between digit and CJK
    out = re.sub(rf"([{CJK_RANGE}])-(\d)", r"\1\2", slug)
    out = re.sub(rf"(\d)-([{CJK_RANGE}])", r"\1\2", out)
    return out


def _normalize(slug: str) -> str:
    """Drop all non-alphanumeric chars for substring matching."""
    return re.sub(r"[^a-z0-9" + CJK_RANGE + r"]", "", slug.lower())


def derive_candidates(
    broken_targets: Iterable[str], existing_ids: set[str]
) -> list[dict]:
    """Apply heuristics in order, returning candidate list."""
    cands: list[dict] = []
    seen_pairs: set[tuple[str, str]] = set()
    existing_list = sorted(existing_ids)

    for target in broken_targets:
        # Skip namespace refs (taxonomy-*, credibility-*, etc.)
        # — they require a different fix path (allow as known namespaces).
        if "-" in target:
            prefix = target.split("-", 1)[0]
            if prefix in {"taxonomy", "credibility", "concepts", "sources", "entities", "synthesis"}:
                continue

        # Heuristic 1: dash noise strip
        stripped = _strip_dash_noise(target)
        if stripped != target and stripped in existing_ids:
            pair = (target, stripped)
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                cands.append({
                    "alias": target,
                    "canonical": stripped,
                    "heuristic": "strip_dash_noise",
                    "confidence": "HIGH",
                    "reason": f"stripped '-' inside CJK/digit boundary",
                })
                continue

        # Heuristic 2: longest prefix match
        best = None
        best_len = 0
        for cand in existing_list:
            if cand.startswith(target) and len(target) >= 4 and len(cand) > len(target):
                if len(target) > best_len:
                    best = cand
                    best_len = len(target)
        if best is not None:
            pair = (target, best)
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                cands.append({
                    "alias": target,
                    "canonical": best,
                    "heuristic": "longest_prefix",
                    "confidence": "HIGH",
                    "reason": f"target is exact prefix of canonical",
                })
                continue

        # Heuristic 3: unique normalized substring
        norm_target = _normalize(target)
        if len(norm_target) >= 4:
            matches = [
                c for c in existing_list
                if norm_target in _normalize(c)
            ]
            if len(matches) == 1:
                pair = (target, matches[0])
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    cands.append({
                        "alias": target,
                        "canonical": matches[0],
                        "heuristic": "unique_substring",
                        "confidence": "MEDIUM",
                        "reason": f"normalized target appears as substring of exactly one canonical",
                    })
    return cands


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--quality-dir", type=Path, default=DEFAULT_QUALITY_DIR)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    qd = args.quality_dir

    # Load broken targets from B3 + B4
    targets: list[str] = []
    for prefix in ("dangling-relations", "broken-wikilinks"):
        path = sorted(qd.glob(f"{prefix}-*.json"))
        if not path:
            print(f"warning: no {prefix} report found in {qd}", file=sys.stderr)
            continue
        data = json.loads(path[-1].read_text(encoding="utf-8", errors="replace"))
        for issue in data.get("issues") or []:
            tgt = issue.get("target")
            if tgt:
                targets.append(tgt)

    unique_targets = sorted(set(targets))
    print(f"Unique broken targets: {len(unique_targets)}")

    existing_ids = _all_existing_ids()
    print(f"Existing wiki IDs: {len(existing_ids)}")

    cands = derive_candidates(unique_targets, existing_ids)
    counts = Counter(c["confidence"] for c in cands)
    print(f"Candidates: HIGH={counts.get('HIGH',0)}  MEDIUM={counts.get('MEDIUM',0)}  LOW={counts.get('LOW',0)}")

    ts = datetime.datetime.now().strftime("%Y%m%d")
    out = qd / f"alias-candidates-{ts}.json"
    summary = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "wiki_root": str(PROJECT_ROOT / "wiki"),
        "total_unique_broken_targets": len(unique_targets),
        "total_existing_ids": len(existing_ids),
        "high_confidence": counts.get("HIGH", 0),
        "medium_confidence": counts.get("MEDIUM", 0),
        "low_confidence": counts.get("LOW", 0),
        "candidates": cands,
    }
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Report: {out}")

    if args.apply:
        sys.path.insert(0, str(REPO_ROOT))
        from src.wiki.features.slug_aliases import SlugAliasRegistry

        reg = SlugAliasRegistry(str(PROJECT_ROOT))
        # Backup registry file if it exists
        if reg._alias_path.exists():
            bak = reg._alias_path.with_suffix(".json.bak." + datetime.datetime.now().strftime("%Y%m%d-%H%M"))
            shutil.copy2(reg._alias_path, bak)
            print(f"Registry backup: {bak}")

        high = [c for c in cands if c["confidence"] == "HIGH"]
        reg.add_many((c["alias"], c["canonical"]) for c in high)
        reg.save()
        print(f"Registered {len(high)} HIGH-confidence aliases via SlugAliasRegistry")
        return 0
    else:
        print("(dry-run; pass --apply to register HIGH-confidence aliases)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
