"""Quality scan for novel-wiki: parse frontmatter, check spec compliance.

Usage:
    python scripts/quality_check_wiki.py [wiki_root]

The wikilink brokenness check goes through the production resolver
(`src.wiki.features.wikilink.resolve_wikilink`) so the report reflects
what users see at render time — including aliases registered in
`.llm-wiki/slug_aliases.json`. After a migration run that adds aliases
the broken count drops in this report, whereas a naive file-existence
check would still show them.
"""
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml
from src.wiki.features.wikilink import resolve_wikilink


ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
    "E:/2026-7-21/ruflo-kb/knowledge/novel-wiki/wiki"
)
# The resolver wants the project root (parent of wiki/), not wiki/
# itself. Cache it once at import time to avoid recomputing per file.
PROJECT_ROOT = ROOT.parent

VALID_TYPES = {"source", "entity", "concept", "synthesis"}
RESERVED_IDS = {"index", "log"}
# CJK cut-over (2026-07-26): allow CJK Unified Ideographs in slugs.
# Alt-2 (pure slug) excludes ``_`` so a malformed UUIDv7 string that
# fails hex check isn't silently accepted via the kebab-case path.
ID_PATTERN = re.compile(
    r"^(?:card_[0-9a-f]{13}_[0-9a-f]{8}_[a-z0-9-一-鿿]+|[a-z0-9-一-鿿]+)$"
)
WIKILINK_PATTERN = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
VALID_TAG_PREFIXES = {
    "genre", "func", "char", "event", "mood", "entity", "scene_phase", "status",
}
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


def split_fm(path: Path):
    """Return (frontmatter_dict, body_str, raw_text)."""
    text = path.read_text(encoding="utf-8")
    m = FRONTMATTER_RE.match(text)
    if not m:
        return None, "", text
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return None, m.group(2), text
    return fm, m.group(2), text


def check_file(path: Path, all_ids: set):
    rel = path.relative_to(ROOT.parent) if path.is_relative_to(ROOT.parent) else path
    issues = []
    fm, body, raw = split_fm(path)

    if fm is None:
        issues.append(("NO_FRONTMATTER", "missing or broken YAML frontmatter"))
        return rel, issues, {}

    page_id = fm.get("id")
    title = fm.get("title")
    ptype = fm.get("type")

    # Required fields
    if page_id is None:
        issues.append(("MISSING_ID", "frontmatter has no id"))
    if title is None or not str(title).strip():
        issues.append(("MISSING_TITLE", "frontmatter has no title"))
    if ptype is None:
        issues.append(("MISSING_TYPE", "frontmatter has no type"))
    elif ptype not in VALID_TYPES:
        issues.append(("BAD_TYPE", f"type={ptype!r} not in {VALID_TYPES}"))

    # id == filename (sans .md)
    if page_id:
        expected = path.stem
        if page_id != expected:
            issues.append((
                "ID_MISMATCH",
                f"id={page_id!r} but filename stem is {expected!r}",
            ))

        # Reserved
        if page_id in RESERVED_IDS:
            issues.append(("RESERVED_ID", f"id={page_id!r} is reserved"))

        # Pattern
        if not ID_PATTERN.match(page_id):
            issues.append((
                "ID_BAD_PATTERN",
                f"id={page_id!r} does not match wiki-spec pattern",
            ))

    # Body
    body_stripped = body.strip()
    body_len = len(body_stripped)
    if body_len == 0:
        issues.append(("EMPTY_BODY", "body is empty"))
    elif body_len < 100:
        issues.append(("SHORT_BODY", f"body length={body_len} < 100 chars"))

    # Tags format
    tags = fm.get("tags") or []
    if isinstance(tags, list):
        bad_tags = []
        for t in tags:
            if not isinstance(t, str):
                continue
            if "/" not in t:
                bad_tags.append(t)
            else:
                prefix = t.split("/", 1)[0]
                if prefix not in VALID_TAG_PREFIXES:
                    bad_tags.append(f"{t} (unknown prefix)")
        if bad_tags:
            issues.append(("TAG_FORMAT", f"non-spec tags: {bad_tags}"))

    # Wikilinks → resolution check (uses production resolver, so
    # aliases registered in .llm-wiki/slug_aliases.json are honored).
    wikilinks = WIKILINK_PATTERN.findall(body)
    broken_links = [
        w for w in wikilinks
        if w not in RESERVED_IDS and not resolve_wikilink(PROJECT_ROOT, w)
    ]
    if broken_links:
        issues.append((
            "BROKEN_WIKILINKS",
            f"{len(broken_links)} wikilinks don't resolve: {sorted(set(broken_links))}",
        ))

    # title heuristic (CJK vs Pinyin)
    title_letters = re.sub(r"[^A-Za-z]", "", str(title or ""))
    if title and not title_letters and ptype != "source":
        # Pure CJK title is fine. But check if the source/folder is also this
        pass

    return rel, issues, {
        "id": page_id,
        "type": ptype,
        "title": title,
        "body_len": body_len,
        "wikilinks": wikilinks,
        "tags": tags,
    }


def main():
    md_files = sorted(ROOT.rglob("*.md"))
    # Pass 1: collect ids (skip index/log reserved)
    page_ids = {}
    by_id = defaultdict(list)
    for p in md_files:
        if p.stem in RESERVED_IDS:
            continue
        fm, _, _ = split_fm(p)
        if fm and "id" in fm:
            page_ids[p] = fm["id"]
            by_id[fm["id"]].append(p)

    # Duplicate detection (multiple files with same id)
    dup_ids = {i: ps for i, ps in by_id.items() if len(ps) > 1}

    all_ids = {pid for pid in page_ids.values() if pid}
    all_ids.update(RESERVED_IDS)

    # Pass 2: quality check
    counter = Counter()
    type_counts = Counter()
    detail = defaultdict(list)
    file_info = {}

    for p in md_files:
        rel, issues, info = check_file(p, all_ids)
        file_info[rel] = info
        for code, msg in issues:
            counter[code] += 1
            detail[code].append((rel, msg))
        type_counts[info.get("type") or "—"] += 1

    # Output
    total = len(md_files)
    pages = total - sum(1 for p in md_files if p.stem in RESERVED_IDS)

    print("=" * 72)
    print(f"Wiki Quality Scan - root: {ROOT}")
    print("=" * 72)
    print(f"\n总文件数: {total} (含 index.md / log.md 各 1)")
    print(f"页面数:   {pages}")
    print(f"按 type 分布:")
    for t, n in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"  {t:12s} {n}")
    print(f"\n唯一 id 数: {len(all_ids - RESERVED_IDS)}")
    if dup_ids:
        print(f"!! 重复 id: {len(dup_ids)}")
        for i, ps in dup_ids.items():
            print(f"   - {i}: {[str(p.relative_to(ROOT.parent)) for p in ps]}")
    else:
        print(f"OK:  所有 id 唯一")

    print(f"\n质量问题统计（{sum(counter.values())} 处）:")
    for code, n in sorted(counter.items(), key=lambda x: -x[1]):
        print(f"  {code:18s} {n}")
        for rel, msg in detail[code][:5]:
            print(f"    - {rel}: {msg[:160]}")
        if len(detail[code]) > 5:
            print(f"    ... 还有 {len(detail[code]) - 5} 处")

    # Pagination stats
    body_lengths = [info["body_len"] for info in file_info.values() if info.get("body_len")]
    if body_lengths:
        body_lengths.sort()
        n = len(body_lengths)
        print(f"\nBody 长度分布（{n} 个页面）:")
        print(f"  min={min(body_lengths)}  median={body_lengths[n // 2]}  "
              f"mean={sum(body_lengths) // n}  max={max(body_lengths)}")
        tiny = [bl for bl in body_lengths if bl < 200]
        print(f"  < 200 字符: {len(tiny)} 个")
        if tiny:
            for rel, info in file_info.items():
                if info.get("body_len", 0) < 200:
                    print(f"    - {rel}  ({info.get('body_len')} 字) title={info.get('title')!r}")


if __name__ == "__main__":
    main()
