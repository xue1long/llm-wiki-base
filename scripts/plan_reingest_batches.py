"""plan_reingest_batches.py — 全量分批重摄入清单生成（plan Phase 4 guidance #1）。

产出 ``<root>/.index/reingest_plan.json``，供 ``batch_executor.py`` 消费：

- 全量 raw 扫描：只含 **.md**（扩展名白名单），排除 ``download_progress.json``
  等非文档文件（F3 同款黑名单 + 扩展名过滤双保险）。
- 批次顺序：**缺口优先**（open gap 的 ``raw_hint`` 命中的 raw 排最前，按
  gap 账本顺序去重）→ **主题目录推进**（剩余 raw 按目录序 + 文件名序稳定排列）。
- 每批 ≤20 个 .md 文件（``--batch-size`` 可调，默认 20）。

清单结构与 phase4_batch 消费的 manifest 兼容（``batches[].files`` 为
项目相对路径 posix 形式，如 ``raw/sources/01_新手入门/foo.md``），
executor 直接按 ``batches[batch_no]`` 索引取文件。

用法::

    PYTHONPATH=. python scripts/plan_reingest_batches.py [--root knowledge/novel-wiki]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.path import normalize_source_path  # noqa: E402

DEFAULT_BATCH_SIZE = 20
# 扩展名白名单 —— 只收 .md（plan Phase 4：每批 ≤20 **md 文件**）。
SUPPORTED_EXTENSIONS = {".md"}
# 文件名黑名单（排除 download_progress.json 等非文档文件）。
EXCLUDED_NAMES = ("download_progress",)
# gap 账本中 raw_hint 的前缀（Phase 3 commit 路径写入的完整相对路径）。
_RAW_SOURCES_MARKER = "raw/sources/"


def _norm_rel(p: Path, root: Path) -> str:
    """Project-relative posix path (``raw/sources/...``)."""
    return p.relative_to(root).as_posix()


def collect_raw_files(root: Path) -> list[str]:
    """All .md files under ``raw/sources/``, sorted by (dir, filename).

    Returns project-relative posix paths.  Non-md extensions and
    blacklisted basenames are excluded here (double filter).
    """
    raw_root = root / "raw" / "sources"
    out: list[str] = []
    if raw_root.is_dir():
        for p in raw_root.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            if any(b in p.name for b in EXCLUDED_NAMES):
                continue
            out.append(_norm_rel(p, root))
    return sorted(out, key=lambda r: (str(Path(r).parent), Path(r).name))


def _normalize_gap_hint(hint: str | None, root: Path) -> str | None:
    """Normalize a gap ``raw_hint`` to project-relative ``raw/sources/...``.

    Phase 3 commit path stored hints as repo-relative full paths
    (``knowledge/novel-wiki/raw/sources/01_新手入门/foo.md``); older or
    absolute hints may take other forms.  Strategy:
    1. strip everything up to the first ``raw/sources/`` marker;
    2. fall back to ``normalize_source_path`` against the project root;
    3. return ``None`` when neither yields a path under ``raw/sources/``.
    """
    if not hint:
        return None
    h = hint.replace("\\", "/")
    idx = h.find(_RAW_SOURCES_MARKER)
    if idx != -1:
        return h[idx:]
    rel = normalize_source_path(h, root)
    if rel.startswith(_RAW_SOURCES_MARKER):
        return rel
    return None


def load_gap_priority(root: Path) -> list[str]:
    """Ordered, deduped raw paths referenced by OPEN gap entries.

    Reads ``.index/knowledge_gaps.json``; only ``status == "open"`` gaps
    count (resolved/suppressed are not priority).  Returns raws that
    actually exist on disk; missing hints are ignored (the executor will
    pick them up by theme progression on a later plan run).
    """
    gap_file = root / ".index" / "knowledge_gaps.json"
    if not gap_file.exists():
        return []
    try:
        data = json.loads(gap_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    priority: list[str] = []
    seen: set[str] = set()
    for g in data.get("gaps") or []:
        if g.get("status") != "open":
            continue
        rel = _normalize_gap_hint(g.get("raw_hint"), root)
        if rel is None or rel in seen:
            continue
        if (root / rel).is_file():
            priority.append(rel)
            seen.add(rel)
    return priority


def build_plan(root: Path, batch_size: int = DEFAULT_BATCH_SIZE) -> dict:
    """Build the full reingest plan manifest for *root*."""
    if batch_size < 1:
        raise ValueError(f"batch_size must be >= 1, got {batch_size}")

    gap_raws = load_gap_priority(root)
    gap_set = set(gap_raws)
    all_raws = collect_raw_files(root)

    ordered: list[str] = []
    ordered.extend(r for r in gap_raws if r in gap_set and (root / r).is_file())
    # Theme progression: remaining raws sorted by (dir, filename).
    remaining = sorted(
        (r for r in all_raws if r not in gap_set),
        key=lambda r: (str(Path(r).parent), Path(r).name),
    )
    ordered.extend(remaining)

    batches: list[dict] = []
    for i in range(0, len(ordered), batch_size):
        chunk = ordered[i:i + batch_size]
        first = Path(chunk[0])
        theme = first.parent.name
        batches.append({
            "theme": theme,
            "batch_no": len(batches),
            "files": chunk,
        })

    skipped = [
        {"path": _norm_rel(p, root), "reason": "non-md"}
        for p in (root / "raw" / "sources").rglob("*")
        if p.is_file() and p.suffix.lower() not in SUPPORTED_EXTENSIONS
    ] + [
        {"path": _norm_rel(p, root), "reason": "excluded_name"}
        for p in (root / "raw" / "sources").rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
        and any(b in p.name for b in EXCLUDED_NAMES)
    ]

    summary = {
        "raw_md_total": len(all_raws),
        "gap_priority_raws": len(gap_raws),
        "batches": len(batches),
        "batch_size": batch_size,
        "note": "Phase 4 全量分批：缺口优先 → 主题目录推进，每批 ≤20 .md",
    }
    return {
        "summary": summary,
        "batches": batches,
        "skipped": skipped,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="全量分批重摄入清单生成")
    ap.add_argument("--root", default="knowledge/novel-wiki",
                    help="project root (default: knowledge/novel-wiki)")
    ap.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    ap.add_argument("--out", default=None, help="output json (default: <root>/.index/reingest_plan.json)")
    args = ap.parse_args(argv)

    root = Path(args.root)
    plan = build_plan(root, batch_size=args.batch_size)
    out = Path(args.out) if args.out else root / ".index" / "reingest_plan.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    s = plan["summary"]
    print(json.dumps(s, ensure_ascii=False, indent=2))
    print(f"\nplan written: {out} ({s['batches']} batches, {s['raw_md_total']} raws)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
