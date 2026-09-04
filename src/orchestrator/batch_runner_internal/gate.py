"""Batch gate helpers and result containers."""
from __future__ import annotations

from dataclasses import dataclass, field

from src.wiki.features.batch_gate import run_precommit_gate


async def _rerun_gate_batch(paths, batch_key, files,
                            batch_page_ids=None) -> bool:
    from src.wiki.storage.page_writer import read_page

    if not batch_page_ids:
        return True
    id_set = set(batch_page_ids)
    pages = []
    for sub in (paths.wiki_sources, paths.wiki_entities,
                paths.wiki_concepts, paths.wiki_synthesis):
        if not sub.exists():
            continue
        for f in sub.glob("*.md"):
            try:
                pg = read_page(f)
            except Exception:
                continue
            if pg.id in id_set:
                pages.append(pg)
    if not pages:
        return True
    passed, issues = run_precommit_gate(pages, [], {}, paths,
                                        allow_overwrite=True)
    if not passed:
        for iss in issues[:10]:
            print(f"  [GATE] {iss}", flush=True)
        print(f"  [GATE] {len(issues)} issue(s) — FAIL", flush=True)
    else:
        print(f"  [GATE] {len(pages)} page(s) — PASS", flush=True)
    return passed


@dataclass
class Batch:
    """单批元数据（对应 manifest 中一个 batch 条目）。"""
    batch_no: int
    theme: str = ""
    files: list[str] = field(default_factory=list)


@dataclass
class GateReport:
    """门禁报告。"""
    passed: bool = True
    issues: list[str] = field(default_factory=list)
