"""Fail-closed series gate must block dry-run when no candidate book proceeds.

Without this guard, ``book build-from-wiki --dry-run`` (and therefore
``build_from_wiki``) would happily produce a rule-only artifact even
when the real baseline numbers show that every candidate book is
auto-downgraded (``merge``/``reference``/``cancel``). That contradicts
the 2026-09-06 plan which mandates "if the baseline can not retain
three books, auto-merge / downgrade / cancel; never fill the gap with
LLM output". The dry-run path is part of the failure contract.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.kc.views.book.wiki.compiler import build_from_wiki
from src.kc.views.book.wiki.model import ContentBlock, PageRecord, WikiSnapshot


def _page(pid: str, taxonomy: str = "book-a", source: bool = True,
          relation_targets=()) -> PageRecord:
    return PageRecord(
        pid, pid, "concept", f"concepts/{pid}.md", taxonomy, "summary",
        (ContentBlock(f"{pid}:0", pid, "Heading", "Body", 0),),
        relation_targets, f"hash-{pid}", 4, None,
        sources=(f"source-{pid}",) if source else (),
    )


def _wiki(tmp_path: Path, *pages: PageRecord) -> Path:
    """Create a wiki tree that survives scan_wiki_snapshot's strict frontmatter rules."""
    root = tmp_path / "wiki"
    for d in ("concepts", "entities", "synthesis"):
        (root / d).mkdir(parents=True, exist_ok=True)
    for page in pages:
        rel = page.path.split("/", 1)[0]
        path = root / page.path
        path.parent.mkdir(parents=True, exist_ok=True)
        # Frontmatter must declare primary_taxonomy so the rule-only series
        # gate can actually attribute pages to candidate books; otherwise the
        # scanner drops them all into "unassigned" and the gate has nothing to
        # downgrade.
        body = (
            "---\n"
            f"id: {page.page_id}\n"
            f"title: {page.title}\n"
            f"type: {page.page_type}\n"
            f"primary_taxonomy: {page.primary_taxonomy}\n"
            f"sources:\n"
            f"  - source-{page.page_id}\n"
            "---\n"
            f"# Heading\n\nbody of {page.page_id}\n"
        )
        path.write_text(body, encoding="utf-8")
    # Minimal project identity so preflight does not fail on E_PROJECT_NOT_INITIALIZED.
    project_json = tmp_path / ".llm-wiki" / "project.json"
    project_json.parent.mkdir(parents=True, exist_ok=True)
    project_json.write_text(json.dumps({
        "id": "00000000-0000-0000-0000-000000000000",
        "name": "rule-only-baseline",
        "schema_version": "v2.0",
    }), encoding="utf-8")
    return root


def test_dry_run_blocks_when_baseline_has_no_retained_candidate(tmp_path: Path) -> None:
    """When the series gate downgrades every candidate book, ``build_from_wiki``
    must return ``status=blocked`` with ``E_SERIES_GATE_NO_RETAINED_CANDIDATE``
    instead of producing a rule-only artifact.
    """
    pages = [
        _page("p1", taxonomy="book-a", source=False),
        _page("p2", taxonomy="book-a", source=False),
        _page("q1", taxonomy="book-b", source=False),
        _page("q2", taxonomy="book-b", source=False),
        _page("r1", taxonomy="book-c", source=False),
    ]
    wiki_root = _wiki(tmp_path, *pages)
    output_dir = tmp_path / "book-wiki"
    output_dir.mkdir()
    # The dry-run gate only fires when the caller opts into a series context
    # via ``--series``. A bare ``build_from_wiki`` on a traditional wiki
    # without series context still produces the historical rule-only artifact.
    result = build_from_wiki(
        wiki_root.parent, output_dir=output_dir, use_llm=False, apply=False,
        series_id="writing-craft", book_id="writing-foundations",
    )
    assert result["status"] == "blocked", result
    codes = result.get("reason_codes") or result.get("errors") or []
    assert "E_SERIES_GATE_NO_RETAINED_CANDIDATE" in codes