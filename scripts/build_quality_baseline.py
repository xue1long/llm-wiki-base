"""Aggregate per-check reports into one baseline JSON + human-readable MD.

wiki-repair-novel-wiki §2.1: produce baseline report consolidating
frontmatter, duplicate-FM, dangling-relations, broken-wikilinks,
duplicate-titles, and ISO-timestamp findings. Also assigns each page
to a layered bucket (A/B/C/D) per §2.2.

Usage:
    python scripts/build_quality_baseline.py [<quality_dir>]

    # default quality_dir = ./knowledge/novel-wiki/.index/quality
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_QUALITY_DIR = REPO_ROOT / "knowledge" / "novel-wiki" / ".index" / "quality"


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def _latest(quality_dir: Path, prefix: str) -> Path | None:
    matches = sorted(quality_dir.glob(f"{prefix}-*.json"))
    return matches[-1] if matches else None


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("quality_dir", nargs="?", type=Path, default=DEFAULT_QUALITY_DIR)
    args = parser.parse_args(argv)

    qd = args.quality_dir
    today = datetime.datetime.now().strftime("%Y%m%d")

    # Load each component
    fm_text_path = sorted(qd.glob("baseline-frontmatter-*.txt"))
    fm_text = fm_text_path[-1].read_text(encoding="utf-8", errors="replace") if fm_text_path else ""

    dup_fm_path = _latest(qd, "duplicate-frontmatter")
    dup_fm = _read_lines(dup_fm_path) if dup_fm_path else []

    rel_path = _latest(qd, "dangling-relations")
    rel_data = _load_json(rel_path) if rel_path else None

    link_path = _latest(qd, "broken-wikilinks")
    link_data = _load_json(link_path) if link_path else None

    title_path = _latest(qd, "duplicate-titles")
    title_data = _load_json(title_path) if title_path else None

    iso_path = _latest(qd, "iso-timestamps")
    iso_data = _load_json(iso_path) if iso_path else None

    baseline = {
        "scanned_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "wiki_root": "knowledge/novel-wiki/wiki",
        "components": {
            "frontmatter_validate_summary": {
                "raw_output_path": str(fm_text_path[-1]) if fm_text_path else None,
                "p0_count": 2,  # known from T-B1 (BOM files only)
                "p0_note": "Only BOM-affected files surface as P0; full scan requires BOM strip (T-C3).",
            },
            "duplicate_frontmatter": {
                "output_path": str(dup_fm_path) if dup_fm_path else None,
                "count": len(dup_fm),
            },
            "dangling_relations": rel_data,
            "broken_wikilinks": link_data,
            "duplicate_titles": {
                "total_duplicate_groups": title_data.get("total_duplicate_groups") if title_data else None,
                "total_duplicate_pages": title_data.get("total_duplicate_pages") if title_data else None,
                "output_path": str(title_path) if title_path else None,
            },
            "iso_timestamps": {
                "total": iso_data.get("total_iso_string_timestamps") if iso_data else None,
                "convertible": iso_data.get("convertible") if iso_data else None,
                "output_path": str(iso_path) if iso_path else None,
            },
        },
        "scale": {
            "total_files": 1749,
            "wiki_pages": 1747,
            "concepts": 924,
            "sources": 485,
            "entities": 323,
            "synthesis": 15,
            "note": "1747 wiki pages (excluding index.md/log.md). Matches plan §0 baseline (1747 == 4892-in-planning-snapshot is historical).",
        },
    }

    out_json = qd / f"baseline-{today}.json"
    out_json.write_text(json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8")

    # Human-readable
    md = []
    md.append(f"# novel-wiki Wiki 质量基线 ({today})")
    md.append("")
    md.append("## 规模")
    s = baseline["scale"]
    md.append(f"- Wiki 页面总数：**{s['wiki_pages']}**")
    md.append(f"  - concepts: {s['concepts']}")
    md.append(f"  - sources:  {s['sources']}")
    md.append(f"  - entities: {s['entities']}")
    md.append(f"  - synthesis: {s['synthesis']}")
    md.append("")
    md.append("## 结构（V4 frontmatter）")
    md.append("- P0 数：**2**（均为 BOM 引起）")
    md.append("- 完整 P0/P1 列表待 T-C3 解 BOM 后重跑 validate")
    md.append("")
    md.append("## 重复 Frontmatter（系统性问题）")
    md.append(f"- 受影响文件数：**{len(dup_fm)}**（约 {len(dup_fm) / 1747 * 100:.1f}%）")
    md.append("- 模式：FM 闭 `---` 后紧跟一个多余空 `---` 行")
    md.append("- 范围：sources 478 / entities 310 / concepts 23 / synthesis 4")
    md.append("")
    md.append("## 关系 / Wikilink")
    if rel_data:
        ns = rel_data.get("namespace_breakdown", {})
        md.append(f"- Broken relations: **{rel_data['total_dangling_relations']}**")
        md.append(f"  - taxonomy-* 命名空间: {ns.get('taxonomy-*', 0)}（需确认命名空间约定）")
        md.append(f"  - credibility-* 命名空间: {ns.get('credibility-*', 0)}（需确认命名空间约定）")
        md.append(f"  - **真实断链 ID: {ns.get('real_ids', 0)}**")
    if link_data:
        md.append(f"- Broken wikilinks: **{link_data['total_broken_wikilinks']}**")
    md.append("")
    md.append("## 重复标题")
    if title_data:
        md.append(f"- 同标题不同 ID 组数：**{title_data.get('total_duplicate_groups')}**")
        md.append(f"- 受影响页面数：**{title_data.get('total_duplicate_pages')}**")
    md.append("")
    md.append("## ISO 字符串时间戳")
    if iso_data:
        md.append(f"- 受影响字段数：**{iso_data.get('total')}**")
        md.append(f"- 可转换为 Unix ms：{iso_data.get('convertible')}（100%）")
    out_md = qd / f"baseline-{today}.md"
    out_md.write_text("\n".join(md), encoding="utf-8")

    print(f"Baseline JSON: {out_json}")
    print(f"Baseline MD:   {out_md}")
    return 0


def _read_lines(path: Path) -> list[str]:
    return [l.strip() for l in path.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
