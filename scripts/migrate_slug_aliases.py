"""One-shot migration: auto-discover slug aliases from existing
broken wikilinks and register them with the SlugAliasRegistry.

Production evidence (novel-wiki 2026-07-26): after multiple LLM
ingests, 10 wikilink targets were unresolvable because the LLM
emitted inconsistent slug variants in different ingests. We
added the registry + resolver hook (commits 2015901 + fc11b1d)
but the existing 10 broken links still show up in the rendered
wiki. This script closes the gap by running heuristics over the
existing wikilink references and registering aliases for any
discoverable match.

Three heuristics (conservative — only auto-register HIGH confidence):

  1. **Longest-prefix match** (`qi-dai-gan` → `qi-dai-gan-chuangzuo`):
     broken target T is exactly a kebab-prefix of an existing slug.
  2. **CJK→pinyin** (`网络文学` → `wangluo-wenxue`):
     broken target contains CJK, pypinyin conversion equals an
     existing slug.
  3. **Unique substring** (`dai-ru-gan` → `dai-qi-gan`):
     broken target's kebab-normalized form appears as a substring
     of exactly one existing slug. (Lower confidence; flagged for
     review even when applied — see MEDIUM entries.)

Anything not matched is left for manual review.

Usage:
    python scripts/migrate_slug_aliases.py [wiki_root]

    # default wiki_root = E:/2026-7-21/ruflo-kb/knowledge/novel-wiki

The script is idempotent: running it twice in a row makes no
additional changes the second time (slug_aliases.add() is a no-op
when alias is already registered).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
RESERVED_IDS = {"index", "log"}


def _normalize(s: str) -> str:
    """Kebab-normalize for substring comparison."""
    return s.lower().replace("_", "").replace("-", "").replace(" ", "")


def _load_existing_slugs(wiki_root: Path) -> set[str]:
    """All page ids currently on disk (across typed directories)."""
    slugs: set[str] = set()
    for f in wiki_root.rglob("*.md"):
        if f.stem in RESERVED_IDS:
            continue
        slugs.add(f.stem)
    return slugs


def _collect_wikilinks(wiki_root: Path) -> list[str]:
    """Every wikilink target across all wiki body texts (de-duped,
    in order of appearance; includes both resolved and broken).
    """
    seen: set[str] = set()
    out: list[str] = []
    for f in wiki_root.rglob("*.md"):
        if f.stem in RESERVED_IDS:
            continue
        text = f.read_text(encoding="utf-8")
        m = FRONTMATTER_RE.match(text)
        body = text[m.end():] if m else text
        for w in WIKILINK_RE.findall(body):
            w = w.strip()
            if w not in seen:
                seen.add(w)
                out.append(w)
    return out


def _cjk_to_pinyin_slug(text: str) -> str | None:
    """Convert CJK segments in ``text`` to kebab-style pinyin.
    Returns None if pypinyin is unavailable or text has no CJK.
    """
    if not CJK_RE.search(text):
        return None
    try:
        import pypinyin  # type: ignore[import-not-found]
    except ImportError:
        return None
    parts = pypinyin.lazy_pinyin(
        text, style=pypinyin.NORMAL, errors=lambda x: list(x)
    )
    # pypinyin.lazy_pinyin returns a list of strings — one per
    # character.  Join with hyphens where the original had them.
    pinyin_chars = [p[0] if isinstance(p, list) else p for p in parts]
    out = []
    for raw_ch, py in zip(text, pinyin_chars):
        if raw_ch in ("-", "_", " "):
            out.append("-")
        elif CJK_RE.match(raw_ch):
            out.append(py.replace(" ", ""))
        else:
            out.append(raw_ch.lower())
    s = "".join(out).strip("-")
    # Collapse repeats introduced by hyphenation
    return re.sub(r"-+", "-", s)


def _candidates_for(target: str, existing: set[str]) -> list[tuple[str, str, str]]:
    """Return list of (slug, confidence, reason) for plausible matches.

    Confidence: "high" | "medium" | "low".
    """
    candidates: list[tuple[str, str, str]] = []

    # Heuristic 1: longest-prefix match (kebab-aware).  HIGH.
    prefix_hits = sorted(
        s for s in existing if s.startswith(target + "-") or s == target
    )
    for s in prefix_hits:
        confidence = "high" if s != target else "high"
        candidates.append((s, confidence, "prefix-match"))

    # Heuristic 2: CJK → pinyin (HIGH if exactly matches).
    pinyin = _cjk_to_pinyin_slug(target)
    if pinyin and pinyin in existing and pinyin != target:
        candidates.append((pinyin, "high", f"cjk-pinyin={pinyin!r}"))

    # Heuristic 3: unique substring match.  MEDIUM if unique, LOW if not.
    norm = _normalize(target)
    substr_hits = sorted(s for s in existing if norm and norm in _normalize(s))
    for s in substr_hits:
        if s == target:
            continue
        conf = "medium" if len(substr_hits) == 1 else "low"
        # Append (don't replace a HIGH from earlier heuristics).
        if all(slug != s for slug, _, _ in candidates):
            candidates.append((s, conf, f"substring({norm})"))

    return candidates


def discover(wiki_root: Path) -> tuple[
    set[str], dict[str, list[tuple[str, str, str]]]
]:
    """Return (broken_targets, proposed_candidates).

    "broken_targets" is the set of wikilink targets that don't
    resolve through the production resolver (exact match).
    proposed_candidates maps each broken target to a list of
    (slug, confidence, reason) tuples returned by _candidates_for.
    """
    existing = _load_existing_slugs(wiki_root)

    # Use the production resolver so "broken" matches what users see.
    sys.path.insert(0, str(wiki_root.parent.parent))  # ensure src/ on path
    from src.wiki.features.wikilink import resolve_wikilink

    all_targets = _collect_wikilinks(wiki_root)
    broken: set[str] = set()
    for t in all_targets:
        if t in RESERVED_IDS:
            continue
        if not resolve_wikilink(wiki_root, t):
            broken.add(t)

    proposed: dict[str, list[tuple[str, str, str]]] = {}
    for t in sorted(broken):
        cands = _candidates_for(t, existing)
        proposed[t] = cands

    return broken, proposed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument(
        "wiki_root",
        nargs="?",
        default=r"E:\2026-7-21\ruflo-kb\knowledge\novel-wiki",
        help="Path to the project directory whose wiki/ subtree "
             "we'll migrate. Defaults to novel-wiki.",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Apply HIGH-confidence aliases to the project's "
             "slug_aliases.json. Without this flag the script is "
             "dry-run only and prints proposals without writing.",
    )
    parser.add_argument(
        "--include-medium", action="store_true",
        help="Also auto-apply MEDIUM confidence aliases (default: HIGH only).",
    )
    args = parser.parse_args()

    wiki_root = Path(args.wiki_root)
    if not (wiki_root / "wiki").exists():
        print(f"ERROR: {wiki_root}/wiki/ not found", file=sys.stderr)
        return 1

    broken, proposed = discover(wiki_root)

    print("=" * 72)
    print(f"Slug alias migration — wiki_root: {wiki_root}")
    print("=" * 72)
    print(f"\nFound {len(broken)} broken wikilink target(s)\n")

    auto: list[tuple[str, str, str]] = []
    manual: list[tuple[str, list[tuple[str, str, str]]]] = []

    for t in sorted(broken):
        cands = proposed[t]
        # Filter to only the highest-confidence candidate(s)
        if cands:
            best_conf = cands[0][1]
            top = [c for c in cands if c[1] == best_conf]
        else:
            top = []
        if top and top[0][1] in ("high",) or (
            args.include_medium and top and top[0][1] in ("high", "medium")
        ):
            for slug, conf, reason in top:
                auto.append((t, slug, reason))
        else:
            manual.append((t, cands))

    print(f"--- AUTO-APPLY ({len(auto)}, HIGH only) ---")
    for t, slug, reason in auto:
        print(f"  {t!r:40s} → {slug!r:40s}  ({reason})")

    print(f"\n--- MANUAL REVIEW ({len(manual)}) ---")
    for t, cands in manual:
        if cands:
            cand_str = ", ".join(f"{s!r}({c})" for s, c, _ in cands)
        else:
            cand_str = "<no heuristic match>"
        print(f"  {t!r:40s} → {cand_str}")

    if not args.apply:
        print("\n(Dry run — re-run with --apply to persist HIGH "
              "confidence aliases.)")
        return 0

    if not auto:
        print("\nNothing to apply.")
        return 0

    from src.wiki.features.slug_aliases import SlugAliasRegistry
    reg = SlugAliasRegistry(wiki_root)
    added = 0
    for t, slug, _ in auto:
        if reg.get_canonical(t) == slug:
            continue  # already registered
        reg.add(t, slug)
        added += 1
        print(f"  + {t!r} → {slug!r}")
    reg.save()

    print(f"\nSaved {added} new alias(es) to "
          f"{wiki_root}/.llm-wiki/slug_aliases.json")

    # Re-scan to report remaining broken
    broken_after, _ = discover(wiki_root)
    newly_resolved = len(broken) - len(broken_after)
    print(f"\nBroken wikilinks: {len(broken)} → {len(broken_after)} "
          f"(resolved {newly_resolved})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
