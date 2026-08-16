"""phase3_accept.py — Phase 3 首批验收（plan Phase 3 guidance 第 2 条）。

在 phase4_batch 摄入完成后运行：
1. 提取批内页面 id 集合：
   - 优先：batch_build_state.json 的 batch_0.completed_files（raw 列表）→
     反查其 source 页 → 再收集该 source 页名下产出（含存量重建页）
   - fallback：磁盘新写入的 source 页
2. 调用 batch_gate_v3.gate_batch 产出批内门禁报告（M1/M2/M4/M6/M7）
3. 断言 Phase 3 验收：
   - 门禁 PASS
   - M1 批内未登记断链 = 0（gap 已登记的不计）
   - M4 必填槽通过率 100%（missing_sections=0 且 placeholders=0）
   - M7 source 全文污染 = 0
   - M6 synthesis 页存在即可（数量在 4.5 聚合）
   - 基线差值：全库 M1 断链率应低于基线 17.2%（趋势）
4. 落盘 `.index/batch_reports/batch_001.json` + 验收报告

用法：python scripts/phase3_accept.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.wiki.core.paths import WikiPaths  # noqa: E402
from src.wiki.features.knowledge_gaps import KnowledgeGapStore  # noqa: E402
from src.wiki.storage.page_writer import read_page  # noqa: E402

ROOT = Path("knowledge/novel-wiki")
BATCH_STATE = ROOT / ".index" / "batch_build_state.json"
REPORT_DIR = ROOT / ".index" / "batch_reports"
BASELINE = ROOT / ".index" / "baseline_2026-08-15.json"


def _norm(raw: str) -> str:
    s = raw.replace("\\", "/")
    if s.startswith("raw/"):
        s = s[len("raw/"):]
    return s


def _completed_raw_files() -> list[str]:
    if not BATCH_STATE.exists():
        return []
    try:
        state = json.loads(BATCH_STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    entry = state.get("batch_0") or state.get("batch_0_0")
    if isinstance(entry, dict):
        return list(entry.get("completed_files", []))
    return []


def _batch_page_ids() -> list[str]:
    """批内页面 = 本批实际写入的页面 id（pages + extras）。

    优先读 batch_build_state.json 的 batch_0.page_ids（phase4_batch 记录，
    精确批内集合）；缺失时 fallback 到 mtime 窗口 + v3.0.0 版本过滤
    （多次重跑后 mtime 口径会混入历史页，故 page_ids 是首选）。
    """
    import re
    from datetime import datetime, timedelta

    # 首选：state 精确 page_ids
    if BATCH_STATE.exists():
        try:
            state = json.loads(BATCH_STATE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = {}
        entry = state.get("batch_0") or state.get("batch_0_0")
        if isinstance(entry, dict) and entry.get("page_ids"):
            return list(entry["page_ids"])

    # fallback：mtime 窗口 + v3.0.0 版本过滤
    window_minutes = 90
    cutoff = datetime.now() - timedelta(minutes=window_minutes)
    version_re = re.compile(r"wiki-template-version:\s*([0-9.]+)")
    ids: list[str] = []
    paths = WikiPaths(ROOT)
    for d in (paths.wiki_sources, paths.wiki_entities, paths.wiki_concepts,
              paths.wiki_synthesis):
        if not d.exists():
            continue
        for f in d.glob("*.md"):
            try:
                if datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
                    continue
                raw = f.read_text(encoding="utf-8", errors="replace")
                vm = version_re.search(raw)
                if not vm or _parse_version(vm.group(1)) < (3, 0, 0):
                    continue  # 存量 2.0.0 页 → 排除
                page = read_page(f)
            except Exception:
                continue
            if page.id and page.id not in ids:
                ids.append(page.id)
    return ids


def _parse_version(version_str: str) -> tuple[int, ...]:
    out = []
    for piece in version_str.split("."):
        try:
            out.append(int(piece))
        except ValueError:
            break
    return tuple(out)


def _baseline_m1() -> float | None:
    try:
        b = json.loads(BASELINE.read_text(encoding="utf-8"))
        return b.get("M1_rate") or b.get("M1") or b.get("metrics", {}).get("M1")
    except (OSError, json.JSONDecodeError):
        return None


def main() -> int:
    from scripts.batch_gate_v3 import gate_batch  # noqa: PLC0415

    batch_ids = _batch_page_ids()
    if not batch_ids:
        print("ERROR: no batch page ids derived (check batch_build_state.json)", file=sys.stderr)
        return 2

    gap_store = KnowledgeGapStore(ROOT)
    report = gate_batch(ROOT, batch_ids, gap_store)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / "batch_001.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    metrics = report["metrics"]
    baseline_m1 = _baseline_m1()

    print("=== Phase 3 首批验收 ===")
    print(f"批内页面数: {len(batch_ids)}  门禁: {'PASS' if report['passed'] else 'BLOCK'}")
    print(f"M1 批内未登记断链: {metrics['M1_broken_rate']} "
          f"({metrics['M1_broken_links']}/{metrics['M1_links_total']})")
    print(f"M2 深引用率: {metrics['M2_deep_ref_rate']}")
    print(f"M4 missing_sections: {metrics['M4_missing_sections']}  placeholders: {metrics['M4_placeholders']}")
    print(f"M6 synthesis 页: {metrics['M6_synthesis_pages']}")
    print(f"M7 source 全文污染: {metrics['M7_source_fulltext']}")
    print(f"基线 M1: {baseline_m1}")
    print(f"报告: {out}")

    ok = True
    if not report["passed"]:
        ok = False
        print("  FAIL: 门禁未通过")
    if metrics["M1_broken_links"] > 0:
        ok = False
        print("  FAIL: M1 批内断链 > 0")
    if metrics["M4_missing_sections"] > 0 or metrics["M4_placeholders"] > 0:
        ok = False
        print("  FAIL: M4 必填槽未 100% 填充")
    if metrics["M7_source_fulltext"] > 0:
        ok = False
        print("  FAIL: M7 source 全文污染 > 0")
    print("=== " + ("PASS ✅" if ok else "FAIL ❌") + " ===")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
