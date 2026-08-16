"""生成 Phase 3 首批清单：缺口优先（B12 中可对齐 raw 的 slug），≤20 个 .md 文件。

输出：knowledge/novel-wiki/.index/reingest_backlog.json（phase4_batch 消费的 manifest 结构）。

首批选择原则（plan Phase 3）：
- 缺口优先 = 被引用但无 source 页的 raw（B12 unreferenced_raw + hallucinated_source_hash，
  二者均可直接对齐 raw 文件名，即缺口消解路径）
- 每批 ≤20 个 .md 文件；过滤 download_progress.json 等非文档文件
- 只含 .md（Phase 3 guidance 第 1 条）
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.slugify import slugify  # noqa: E402
from src.wiki.core.paths import WikiPaths  # noqa: E402
from src.wiki.features.metrics import census_wiki, collect_wikilinks, page_ids  # noqa: E402

ROOT = Path("knowledge/novel-wiki")
OUT = ROOT / ".index" / "reingest_backlog.json"

_HASH_SUFFIX_RE = re.compile(r"-[0-9a-f]{8}$")


def _norm(slug: str) -> str:
    return re.sub(r"[\s\-_，,、。.!！?？·（）()【】\[\]]+", "", slug).lower()


def main() -> int:
    paths = WikiPaths(ROOT)
    snaps = census_wiki(paths)
    known_ids = page_ids(snaps)
    known_norm = {_norm(s) for s in known_ids}

    raw_md = sorted(p for p in paths.raw_sources.rglob("*.md") if p.is_file())
    raw_stems = {p.stem for p in raw_md}
    raw_norm = {_norm(s) for s in raw_stems}

    # 完整 B12 分类（不截断 examples）
    broken: dict[str, set[str]] = {"unreferenced_raw": set(), "hallucinated_source_hash": set(), "other": set()}
    for snap in snaps:
        for target in collect_wikilinks(snap):
            tn = _norm(target)
            if target in known_ids or tn in known_norm:
                continue
            if _HASH_SUFFIX_RE.search(target):
                broken["hallucinated_source_hash"].add(target)
            elif tn in raw_norm or any(tn in rn or rn in tn for rn in raw_norm):
                broken["unreferenced_raw"].add(target)
            else:
                broken["other"].add(target)

    # slug -> raw 映射（直接 slug 或剥离 -8hex 后缀）
    slug_to_raw: dict[str, list[Path]] = {}
    for p in raw_md:
        slug_to_raw.setdefault(slugify(p.stem), []).append(p)

    def match(slug: str):
        if slug in slug_to_raw:
            return slug_to_raw[slug]
        m = _HASH_SUFFIX_RE.search(slug)
        if m and slug[: m.start()] in slug_to_raw:
            return slug_to_raw[slug[: m.start()]]
        return None

    # 缺口优先候选：unreferenced_raw + hallucinated_source_hash 中可对齐 raw 的
    cands: list[dict] = []
    for cat in ("unreferenced_raw", "hallucinated_source_hash"):
        for slug in sorted(broken[cat]):
            m = match(slug)
            if m:
                cands.append({"slug": slug, "raw": m[0].relative_to(ROOT).as_posix(), "cat": cat})
    # 去重（同一 raw 可能被多个 slug 命中）
    seen_raw: set[str] = set()
    uniq: list[dict] = []
    for c in cands:
        if c["raw"] not in seen_raw:
            seen_raw.add(c["raw"])
            uniq.append(c)

    # 过滤：排除 download_progress 等非文档文件（.md 白名单已保证；再按文件名黑名单）
    BLACK = ("download_progress",)
    uniq = [c for c in uniq if not any(b in Path(c["raw"]).name for b in BLACK)]

    # 首批排除超长文档（>8000 字符，generator 截断阈值）：长文档走 chunked 是
    # Phase 4 独立决策（B1），Phase 3 首批只收单次生成可覆盖的教程类文件。
    MAX_CHARS = 8000
    in_range, deferred_long = [], []
    for c in uniq:
        n = len((ROOT / c["raw"]).read_text(encoding="utf-8", errors="replace"))
        (in_range if n <= MAX_CHARS else deferred_long).append(c)
    files = [c["raw"] for c in in_range[:20]]
    summary = {
        "raw_md_total": len(raw_md),
        "broken_unreferenced_raw": len(broken["unreferenced_raw"]),
        "broken_hallucinated_source_hash": len(broken["hallucinated_source_hash"]),
        "broken_other": len(broken["other"]),
        "gap_candidates_matched": len(uniq),
        "deferred_long_docs": len(deferred_long),
        "batch_files": len(files),
        "note": "Phase 3 首批：缺口优先（B12 可对齐 raw），≤20 .md，排除 >8000 字符长文档",
    }
    manifest = {
        "summary": summary,
        "batches": [{
            "theme": "gap-first",
            "batch_no": 1,
            "files": files,
        }],
        "long_docs": [{"path": c["raw"], "chars": len((ROOT / c["raw"]).read_text(encoding="utf-8", errors="replace"))} for c in deferred_long],
        "skipped": [{"path": c["raw"], "reason": "gap_deferred", "detail": c["slug"]} for c in in_range[20:]],
    }
    OUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\n--- batch_001 files ---")
    for f in files:
        print(f"  {f}")
    print(f"\nmanifest written: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
