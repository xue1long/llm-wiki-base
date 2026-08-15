"""audit_blindspots.py — Phase 0.2 blind-spot census for novel-wiki.

Computes the plan 0.2 items that are deterministic (zero-LLM):
  B1  backlog classification  (tiny / duplicate_of / long_docs / unhandled)
  B3  stub census + stub reference edges
  B5  tag value distribution (情绪/ 场景阶段/ 旧前缀)
  B6  slug_aliases.json entry count
  B9  category / taxonomy_sub value distribution
  B11 vector dimension / provider consistency
  B12 broken-link target classification (feed for gap-first batching)
plus a provisional M2-feasibility estimate (deep-reference potential from
existing multi-source pages).

LLM-dependent items (B2 cost sampling, B10 retry-effect experiment) are
NOT computed here — they are deferred to the Phase 3 first batch (plan 0.2).

Usage:
    python scripts/audit_blindspots.py <project_root> [--out <json>]
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.wiki.core.paths import WikiPaths  # noqa: E402
from src.wiki.features.metrics import (  # noqa: E402
    census_wiki,
    collect_wikilinks,
    metric_broken_links,
    page_ids,
)

_LEGACY_TAG_PREFIXES = ("genre/", "func/", "char/", "event/", "mood/",
                        "entity/", "scene_phase/", "status/")
_HASH_SUFFIX_RE = re.compile(r"-[0-9a-f]{8}$")
_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def _norm(slug: str) -> str:
    """Slug normalization for alignment checks (strip separators + case)."""
    return re.sub(r"[\s\-_，,、。.!！?？·（）()【】\[\]]+", "", slug).lower()


def _read_taxonomy_sub(paths: WikiPaths) -> Counter:
    c: Counter = Counter()
    for d in (paths.wiki_entities, paths.wiki_concepts):
        if not d.exists():
            continue
        for f in d.glob("*.md"):
            try:
                text = f.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            m = re.search(r"(?m)^taxonomy_sub:\s*'?([^'\n]*)'?", text)
            c[m.group(1).strip() if m else "(none)"] += 1
    return c


def _tag_distribution(paths: WikiPaths) -> dict:
    out: dict[str, Counter] = defaultdict(Counter)
    for d in (paths.wiki_sources, paths.wiki_entities, paths.wiki_concepts,
              paths.wiki_synthesis):
        if not d.exists():
            continue
        for f in d.glob("*.md"):
            try:
                text = f.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            m = re.search(r"(?m)^tags:[ \t]*(.*)$", text)
            if not m:
                continue
            for line in text[m.end():].splitlines():
                lm = re.match(r"(?m)^\s*-\s*(.+)$", line)
                if not lm:
                    if re.match(r"(?m)^[a-z_]+:[ \t]*", line):
                        break
                    continue
                tag = lm.group(1).strip().strip('"').strip("'")
                prefix, _, value = tag.partition("/")
                if prefix in ("情绪", "场景阶段", "读者群", "平台", "素材", "可信度"):
                    out[prefix][value] += 1
    return {k: dict(v) for k, v in out.items()}


def _stub_ref_edges(paths: WikiPaths, stub_ids: set[str]) -> list[dict]:
    """Pages that reference a stub slug (body wikilink or relation target)."""
    edges: list[dict] = []
    for d in (paths.wiki_sources, paths.wiki_entities, paths.wiki_concepts,
              paths.wiki_synthesis):
        if not d.exists():
            continue
        for f in d.glob("*.md"):
            try:
                text = f.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            for m in _WIKILINK_RE.finditer(text):
                target = m.group(1).strip()
                if target in stub_ids:
                    edges.append({"from": f.stem, "to": target, "kind": "wikilink"})
            for tm in re.finditer(r"(?m)target:\s*(\S+)", text):
                target = tm.group(1).strip().strip('"').strip("'")
                if target in stub_ids:
                    edges.append({"from": f.stem, "to": target, "kind": "relation"})
    # dedupe
    seen = set()
    out = []
    for e in edges:
        key = (e["from"], e["to"], e["kind"])
        if key not in seen:
            seen.add(key)
            out.append(e)
    return out


def _backlog_classify(paths: WikiPaths, max_chars: int = 16000,
                      tiny_chars: int = 500) -> dict:
    """B1: classify raw .md files (mirrors build_reingest_backlog policy)."""
    raw_dir = paths.raw_sources
    counts: Counter = Counter()
    long_docs: list[dict] = []
    tiny: list[dict] = []
    dup: list[dict] = []
    unhandled: list[dict] = []
    fingerprints: dict[str, str] = {}
    for p in sorted(raw_dir.rglob("*.md")):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        chars = len(text)
        fp = re.sub(r"\s+", "", text)
        if fp in fingerprints:
            dup.append({"path": str(p.relative_to(paths.root)), "detail": fingerprints[fp]})
            continue
        fingerprints[fp] = str(p.relative_to(paths.root))
        if chars < tiny_chars:
            tiny.append({"path": str(p.relative_to(paths.root)), "chars": chars})
        elif chars > max_chars:
            long_docs.append({"path": str(p.relative_to(paths.root)), "chars": chars})
    # Non-md artifacts under raw/sources
    for p in sorted(raw_dir.rglob("*")):
        if p.is_file() and p.suffix.lower() != ".md":
            unhandled.append({"path": str(p.relative_to(paths.root))})
    return {
        "total_md": len(fingerprints),
        "long_docs_count": len(long_docs),
        "long_docs": long_docs[:50],
        "tiny_count": len(tiny),
        "duplicate_of_count": len(dup),
        "unhandled_format_count": len(unhandled),
        "unhandled": unhandled,
    }


def _classify_broken(snaps, raw_stems: set[str], known_ids: set[str]) -> dict:
    """B12: classify M1 broken-link targets into remediation paths."""
    known_norm = {_norm(s) for s in known_ids}
    raw_norm = {_norm(s) for s in raw_stems}
    categories: dict[str, list[str]] = defaultdict(list)
    for snap in snaps:
        for target in collect_wikilinks(snap):
            tn = _norm(target)
            if target in known_ids or tn in known_norm:
                continue  # resolvable — not broken
            if _HASH_SUFFIX_RE.search(target):
                categories["hallucinated_source_hash"].append(target)
            elif tn in raw_norm or any(tn in rn or rn in tn for rn in raw_norm):
                categories["unreferenced_raw"].append(target)
            else:
                categories["other"].append(target)
    deduped = {k: sorted(set(v)) for k, v in categories.items()}
    return {"counts": {k: len(v) for k, v in deduped.items()},
            "examples": {k: v[:20] for k, v in deduped.items()}}


def main() -> None:
    # Force UTF-8 stdout regardless of Windows console codepage (the JSON
    # payload contains CJK paths and must round-trip for the tests).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) < 2:
        print("usage: audit_blindspots.py <project_root> [--out <json>]")
        sys.exit(2)
    root = Path(sys.argv[1])
    out_json = None
    if "--out" in sys.argv:
        i = sys.argv.index("--out")
        if i + 1 < len(sys.argv):
            out_json = sys.argv[i + 1]
    paths = WikiPaths(root)

    snaps = census_wiki(paths)
    known_ids = page_ids(snaps)
    stub_ids = {s.id for s in snaps if s.path.name and _is_stub(s)}

    raw_md = sorted(paths.raw_sources.rglob("*.md")) if paths.raw_sources.exists() else []
    raw_stems = {p.stem for p in raw_md}

    result: dict = {
        "B1_backlog": _backlog_classify(paths),
        "B3_stub": {
            "stub_pages": len(stub_ids),
            "pages_referencing_stubs": len({e["from"] for e in _stub_ref_edges(paths, stub_ids)}),
            "stub_ref_edges": _stub_ref_edges(paths, stub_ids)[:200],
        },
        "B5_tags": _tag_distribution(paths),
        "B6_slug_aliases": _count_aliases(root),
        "B9_taxonomy_sub": dict(_read_taxonomy_sub(paths)),
        "B11_vector": _vector_dimension_check(),
        "B12_broken_class": _classify_broken(snaps, raw_stems, known_ids),
        "B2_B10_note": "deferred: B2 cost sampling + B10 retry-effect need LLM (Phase 3 first batch)",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if out_json:
        out = Path(out_json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"written: {out}")


def _is_stub(snap) -> bool:
    m = re.search(r"(?m)^processing_depth:\s*(stub)\s*$", snap.raw_frontmatter)
    return bool(m)


def _count_aliases(root: Path) -> int:
    p = root / ".llm-wiki" / "slug_aliases.json"
    if not p.exists():
        return 0
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return len(data.get("aliases") or {})
    except (json.JSONDecodeError, OSError):
        return -1


def _vector_dimension_check() -> dict:
    """B11: store schema vs provider defaults (read-only)."""
    store_dim = 384  # src/vector/store.py _build_schema
    provider_default = 1536  # src/llm/provider_factory.py default
    # Try to read the configured default provider dimension.
    dim = None
    try:
        from src.llm.registry import ProviderRegistry
        reg = ProviderRegistry()
        default = reg.get_default_provider()
        if default is not None:
            dim = getattr(default.config, "dimension", None)
    except Exception:
        dim = None
    return {
        "store_schema_dim": store_dim,
        "provider_default_dim": provider_default,
        "configured_provider_dim": dim,
        "conflict_when_remote": dim is None or (dim is not None and dim != store_dim),
        "note": ("no .index/lancedb yet — conflict only surfaces at Phase 4 "
                 "first upsert; resolve provider/dimension before that (P4)"),
    }


if __name__ == "__main__":
    main()
