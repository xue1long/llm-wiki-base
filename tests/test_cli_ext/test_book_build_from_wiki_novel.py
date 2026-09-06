"""Integration: build_from_wiki uses NOVEL_WIKI_PROFILE when --series matches.

Plan: docs/superpowers/plans/2026-09-06-novel-wiki-book-series-compile-enable.md
Slice S3: compiler.py wiring + cli_ext integration test.

The real novel-wiki project has 写作技法 with 540 concept pages and 1
synthesis page. With NOVEL_WIKI_PROFILE and chapter_exit_evidence
auto-derived, the gate must produce at least one proceed candidate so
``build_from_wiki(..., series_id="写作技法", book_id="写作技法", apply=False)``
returns ``status=planned`` instead of ``status=blocked``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def _make_novel_wiki_minimal(root: Path) -> Path:
    """Create a minimal novel-wiki-shaped project under root.

    Mirrors the real wiki structure: 540 concept + 1 synthesis in
    写作技法 taxonomy, with supports edges from concept → synthesis.
    """
    wiki = root / "wiki"
    for d in ("concepts", "entities", "synthesis"):
        (wiki / d).mkdir(parents=True, exist_ok=True)
    synth_id = "wc-s0"
    for i in range(540):
        (wiki / "concepts" / f"wc-c{i}.md").write_text(
            "---\n"
            f"id: wc-c{i}\n"
            f"title: concept {i}\n"
            "type: concept\n"
            "primary_taxonomy: 写作技法\n"
            "sources:\n"
            f"  - source-wc-c{i}\n"
            "relations:\n"
            f"  - target: {synth_id}\n"
            "    type: supports\n"
            "---\n"
            f"# Heading\n\nbody of wc-c{i}\n",
            encoding="utf-8",
        )
    (wiki / "synthesis" / f"{synth_id}.md").write_text(
        "---\n"
        f"id: {synth_id}\n"
        f"title: synthesis 0\n"
        "type: synthesis\n"
        "primary_taxonomy: 写作技法\n"
        "sources:\n"
        f"  - source-{synth_id}\n"
        "---\n"
        "# Synthesis\n\nbody of synthesis\n",
        encoding="utf-8",
    )
    (root / ".llm-wiki").mkdir(exist_ok=True)
    (root / ".llm-wiki" / "project.json").write_text(
        '{"id":"00000000-0000-0000-0000-000000000000","name":"novel-wiki-test","schema_version":"v2.0"}',
        encoding="utf-8",
    )
    return wiki


def test_build_from_wiki_with_novel_wiki_series_returns_planned(tmp_path: Path) -> None:
    """When --series matches a NOVEL_WIKI_PROFILE taxonomy, dry-run must
    reach status=planned instead of blocked by the gate."""
    from src.kc.views.book.wiki.compiler import build_from_wiki

    root = tmp_path / "novel-wiki-mini"
    root.mkdir()
    _make_novel_wiki_minimal(root)
    output = root / "book-wiki"
    output.mkdir()

    result = build_from_wiki(
        root, output_dir=output, use_llm=False, apply=False,
        series_id="写作技法", book_id="写作技法",
    )

    assert result["status"] == "planned", result
    assert result.get("series_id") == "写作技法"
    assert "version_dir" in result


def test_build_from_wiki_with_unknown_series_still_blocks(tmp_path: Path) -> None:
    """Series not in NOVEL_WIKI_PROFILE keeps the strict default path and
    remains blocked — the relax only applies to known novel-wiki
    taxonomies, never silently expands to user-typed strings."""
    from src.kc.views.book.wiki.compiler import build_from_wiki

    root = tmp_path / "novel-wiki-mini"
    root.mkdir()
    _make_novel_wiki_minimal(root)
    output = root / "book-wiki"
    output.mkdir()

    result = build_from_wiki(
        root, output_dir=output, use_llm=False, apply=False,
        series_id="writing-craft", book_id="writing-foundations",
    )

    # writing-craft is not in NOVEL_WIKI_PROFILE.candidate_taxonomies so the
    # strict default path runs. The real novel-wiki has no taxonomy named
    # "writing-craft", so candidate_pages are empty → decision=cancel →
    # no retained candidate → gate blocks.
    print("DEBUG result:", result)
    assert result["status"] == "blocked", result
    assert result.get("series_id") == "writing-craft"
    assert "E_SERIES_GATE_NO_RETAINED_CANDIDATE" in result["reason_codes"]


def test_dry_run_does_not_overwrite_current_pointer(tmp_path: Path) -> None:
    """Red line #4: dry-run must not write CURRENT.json. We pre-place a
    pointer at a known run_id and assert it stays byte-identical."""
    from src.kc.views.book.wiki.compiler import build_from_wiki

    root = tmp_path / "novel-wiki-mini"
    root.mkdir()
    _make_novel_wiki_minimal(root)
    output = root / "book-wiki"
    output.mkdir()

    prior = {"version": "prior-release", "manifest_sha256": "deadbeef"}
    pointer = output / "CURRENT.json"
    pointer.write_text(json.dumps(prior, ensure_ascii=False) + "\n",
                       encoding="utf-8")

    build_from_wiki(
        root, output_dir=output, use_llm=False, apply=False,
        series_id="写作技法", book_id="写作技法",
    )

    assert pointer.read_text(encoding="utf-8") == json.dumps(
        prior, ensure_ascii=False) + "\n", "CURRENT.json must not be touched by dry-run"
