"""batch_gate_v3.py — post-ingest batch gate (plan 1.5 / spec §5.3).

Runs, in order, for a batch's page set:
1. NDG gate (P1–P7, reused from batch_gate_check via run_ndg_gate) — the
   write-time gate phase4_batch already applies pre-commit.
2. lint on the batch scope only (lint_wiki(page_ids=...)) — MISSING-SECTION
   (ERROR) / placeholder / illegal-relation / synthesis-gate / RAW-PASTE.
3. Broken-link reconciliation vs 磁盘页 ∪ SlugAliasRegistry ∪ 索引 (M1;
   gap-registered slugs are NOT counted — F2 semantics; the store records
   them separately via knowledge_gaps).
4. Tag value-domain compliance (1.4 enum set).

Any ERROR (or NDG blocker / lint ERROR / M1 unresolved) → batch blocked.

Writes a batch report JSON (`.index/batch_reports/<name>.json`) carrying
M1/M2/M4/M6/M7 for the batch scope plus an LLM-cost placeholder field
(M10b — filled by the executor).

Usage:
    python scripts/batch_gate_v3.py <wiki_root> --report <name> \
        --pages id1,id2,... [--llm-calls N] [--tokens N]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.wiki.core.paths import WikiPaths  # noqa: E402
from src.wiki.features.batch_reconcile import reconcile_batch  # noqa: E402
from src.wiki.features.indexer import read_index  # noqa: E402
from src.wiki.features.knowledge_gaps import KnowledgeGapStore  # noqa: E402
from src.wiki.features.lint import LintSeverity, lint_wiki  # noqa: E402
from src.wiki.features.metrics import (  # noqa: E402
    census_wiki,
    metric_broken_links,
    metric_deep_reference_rate,
    metric_slot_compliance,
    metric_source_fulltext_pollution,
    metric_synthesis_count,
    page_ids,
)
from src.wiki.features.ndg_gate import run_ndg_gate  # noqa: E402
from src.wiki.storage.page_writer import read_page  # noqa: E402


def gate_batch(wiki_root: Path, batch_ids: list[str], gap_store: KnowledgeGapStore,
               llm_calls: int = 0, tokens: int = 0) -> dict:
    """Run the full batch gate; returns a report dict with pass/fail."""
    paths = WikiPaths(wiki_root)
    report: dict = {
        "passed": True,
        "issues": [],
        "metrics": {},
        "cost": {"llm_calls": llm_calls, "tokens": tokens},
        "scanned_pages": 0,
    }

    # Load batch pages (missing → blocker).
    files: list[Path] = []
    for d in (paths.wiki_sources, paths.wiki_entities, paths.wiki_concepts,
              paths.wiki_synthesis):
        if not d.exists():
            continue
        for f in d.glob("*.md"):
            try:
                page = read_page(f)
            except Exception:
                continue
            if page.id in set(batch_ids):
                files.append(f)
    if len(files) != len(set(batch_ids)):
        report["passed"] = False
        report["issues"].append(
            {"code": "BATCH-MISSING-PAGE", "severity": "error",
             "message": f"found {len(files)}/{len(set(batch_ids))} batch pages"})

    pages = [read_page(f) for f in files]
    report["scanned_pages"] = len(pages)
    known_ids = page_ids(census_wiki(paths))

    # 1. NDG gate (reuse batch_gate_check semantics: reconcile → ndg)
    try:
        reconcile = reconcile_batch(pages, paths=paths)
        if reconcile.conflicts:
            report["passed"] = False
            for c in reconcile.conflicts:
                report["issues"].append(
                    {"code": "RECONCILE", "severity": "error",
                     "page_id": c.slug,
                     "message": f"cross-type slug conflict {list(c.types)}"})
        ndg = run_ndg_gate(reconcile.pages, extra_pages=reconcile.extras, paths=paths)
        for issue in ndg.issues:
            if issue.is_blocker:
                report["passed"] = False
                report["issues"].append(
                    {"code": issue.code, "severity": "error",
                     "page_id": issue.page_id or "",
                     "message": issue.message})
    except Exception as exc:  # ndg failure = block
        report["passed"] = False
        report["issues"].append(
            {"code": "NDG-ERROR", "severity": "error", "message": str(exc)})

    # 2. lint on batch scope (1.8 page_ids)
    lint = lint_wiki(paths, project_id="batch", page_ids=set(batch_ids))
    missing_c, placeholder_c, other_c = metric_slot_compliance(lint)
    for issue in lint.issues:
        if issue.severity == LintSeverity.ERROR:
            report["passed"] = False
        report["issues"].append(
            {"code": issue.code, "severity": issue.severity.value,
             "page_id": issue.page_id or "", "message": issue.message})

    # 3. broken links (M1; gap not counted)
    snaps = [s for s in census_wiki(paths) if s.id in set(batch_ids)]
    try:
        from src.wiki.features.slug_aliases import SlugAliasRegistry
        reg = SlugAliasRegistry(wiki_root)
        alias = reg.get_canonical
    except Exception:
        alias = None
    index_ids = {slug for slug, _, _ in read_index(paths)}
    # Phase 3 实测：M1 判定归一 slug 变体（双横线 vs 单横线等），避免假断链。
    from src.wiki.features.slug_utils import normalize_reconcile_slug
    known_norm = {normalize_reconcile_slug(s) for s in known_ids | index_ids}
    m1 = metric_broken_links(snaps, known_ids | index_ids, alias_canonical=alias,
                             known_norm=known_norm)
    gap_slugs = {g.slug for g in gap_store.all() if g.status in ("open", "suppressed")}
    # Phase 3 follow-up C：gap 剔除用归一化匹配（gap slug 可能是变体，
    # 如双横线 vs 单横线），防止 gap 已登记但仍被计为 M1 断链。
    gap_norm = {normalize_reconcile_slug(s) for s in gap_slugs}
    unresolved = [s for s in m1.broken_slugs
                  if s not in gap_slugs and normalize_reconcile_slug(s) not in gap_norm]
    if unresolved:
        report["passed"] = False
        report["issues"].append(
            {"code": "BROKEN-LINK", "severity": "error",
             "message": f"{len(unresolved)} unresolved links not in gap ledger"})

    # 4. tag value compliance (1.4)
    from src.wiki.features.tag_namespace import validate_tag_compliance, TagValidationError
    for page in pages:
        try:
            validate_tag_compliance(page.tags or [])
        except TagValidationError as exc:
            report["passed"] = False
            report["issues"].append(
                {"code": "TAG-ENUM", "severity": "error", "page_id": page.id,
                 "message": str(exc)})

    # Metrics (batch scope)
    raw_md = list(paths.raw_sources.rglob("*.md")) if paths.raw_sources.exists() else []
    m2_rate, m2_ref, m2_total = metric_deep_reference_rate(
        snaps, raw_md, project_root=wiki_root)
    report["metrics"] = {
        "M1_broken_rate": round(m1.rate, 4),
        "M1_broken_links": m1.broken_links,
        "M1_links_total": m1.total_links,
        "M2_deep_ref_rate": round(m2_rate, 4),
        "M4_missing_sections": missing_c,
        "M4_placeholders": placeholder_c,
        "M6_synthesis_pages": metric_synthesis_count(paths),
        "M7_source_fulltext": metric_source_fulltext_pollution(snaps),
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="post-ingest batch gate (plan 1.5)")
    parser.add_argument("wiki_root", type=Path)
    parser.add_argument("--report", required=True, help="report name, e.g. batch_001")
    parser.add_argument("--pages", required=True, help="comma-separated batch page ids")
    parser.add_argument("--llm-calls", type=int, default=0)
    parser.add_argument("--tokens", type=int, default=0)
    args = parser.parse_args(argv)

    batch_ids = [s.strip() for s in args.pages.split(",") if s.strip()]
    gap_store = KnowledgeGapStore(args.wiki_root)
    report = gate_batch(args.wiki_root, batch_ids, gap_store,
                        llm_calls=args.llm_calls, tokens=args.tokens)

    report_dir = args.wiki_root / ".index" / "batch_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    out = report_dir / f"{args.report}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(f"[gate-v3] {len(report['issues'])} issue(s), "
          f"{'PASS' if report['passed'] else 'BLOCK'} -> {out}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
