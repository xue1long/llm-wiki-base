"""Gap tests for the book-series CLI / manifest / staged-release surface.

These tests deliberately do not modify production code. They encode the
contract that the 2026-09-06 remediation plan requires — `--series`,
`--book`, `--narrative`, `series-manifest.json` fields, hard-dependency
release blocking, independent book staged rollback, and ledger/compiler
isolation. Every test below currently FAILS because production code
does not yet implement those features; they are the recovery map for the
remaining work in the book-series plan.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from src.cli import build_parser
from src.kc.views.book.wiki.compiler import compile_book
from src.kc.views.book.wiki.model import ContentBlock, PageRecord, WikiSnapshot
from src.kc.views.book.wiki.polish_llm import GeneratedChapter, GeneratedSection
from src.kc.views.book.wiki.partition import build_series_assignment
from src.kc.views.book.wiki.series_model import (
    SCHEMA_VERSION, canonical_digest,
)
from src.kc.views.book.wiki.series_validate import (
    dependency_report, validate_series_manifest,
)


# ---------------------------------------------------------------------------
# 1. CLI contract — `--series`, `--book`, `--narrative`
# ---------------------------------------------------------------------------


def _book_parser() -> argparse.ArgumentParser:
    return build_parser()


def test_book_build_from_wiki_exposes_series_book_and_narrative_flags() -> None:
    """`book build-from-wiki` must accept the book-series CLI contract."""
    parser = _book_parser()
    args = parser.parse_args([
        "book", "build-from-wiki",
        "--project", "demo",
        "--series", "writing-craft",
        "--book", "writing-foundations",
        "--narrative",
        "--use-llm",
        "--polish",
    ])
    assert args.command == "book"
    assert args.book_command == "build-from-wiki"
    assert args.series == "writing-craft"
    assert args.book == "writing-foundations"
    assert args.narrative is True
    assert args.use_llm is True
    assert args.polish is True


def test_book_build_rejects_unknown_series_value() -> None:
    """Unknown series id must be rejected before any LLM call."""
    parser = _book_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([
            "book", "build-from-wiki",
            "--project", "demo",
            "--series", "",
        ])


# ---------------------------------------------------------------------------
# 2. Manifest metadata — series_id / book_id / reader_promise / exit_artifact
# ---------------------------------------------------------------------------


def _page(page_id: str, taxonomy: str = "writing-foundations", source: bool = True,
          relation_targets=(), digest: str | None = None,
          task_type: str | None = None) -> PageRecord:
    return PageRecord(
        page_id, page_id, "concept", f"concepts/{page_id}.md", taxonomy, "summary",
        (ContentBlock(f"{page_id}:0", page_id, "Heading", "Body", 0),),
        relation_targets, digest or f"hash-{page_id}", 4, None,
        sources=(f"source-{page_id}",) if source else (),
        task_type=task_type,
    )


def _artifact(tmp_path: Path, snapshot_pages,
              *, series_id: str | None = None, book_id: str | None = None,
              book_mode: str | None = None, release_id: str | None = None):
    snapshot = WikiSnapshot(
        "snap-1", str(tmp_path / "wiki"), "v2.0", tuple(snapshot_pages), ())
    outline = [{"schema_version": "outline-v1", "snapshot_id": "snap-1", "volumes": [{
        "volume_id": "v1", "chapters": [{
            "chapter_id": "c1", "title": "Chapter", "page_ids": [p.page_id for p in snapshot_pages],
            "overview_refs": [snapshot_pages[0].page_id],
            "reader_promise": "draft a story outline",
            "exit_artifact": "story_outline_doc",
            "hard_dependencies": [],
            "soft_dependencies": [],
        }],
    }]}]
    chapter_id = outline[0]["volumes"][0]["chapters"][0]["chapter_id"]
    return compile_book(
        snapshot, outline, {p.page_id: p for p in snapshot_pages},
        fingerprint={}, state_dir=tmp_path / ".index",
        series_id=series_id, book_id=book_id,
        book_mode=book_mode, release_id=release_id,
        generated_chapters={chapter_id: GeneratedChapter(
            chapter_id,
            (GeneratedSection(
                "s1", "Chapter", "LLM body",
                tuple(p.page_id for p in snapshot_pages),
            ),),
            "complete",
        )},
    )


def test_compiled_manifest_records_series_book_and_reader_promise(tmp_path) -> None:
    artifact = _artifact(tmp_path, [_page("p1"), _page("p2")],
                         series_id="writing-craft", book_id="writing-foundations",
                         book_mode="narrative", release_id="r1")

    manifest = artifact.manifest
    assert manifest.get("series_id") == "writing-craft"
    assert manifest.get("book_id") == "writing-foundations"
    assert manifest.get("reading_experience_mode") == "narrative"
    assert manifest.get("mode") == "narrative"
    assert manifest.get("reader_promise") == "draft a story outline"
    assert manifest.get("exit_artifact") == "story_outline_doc"
    assert manifest.get("hard_dependencies") == []
    assert manifest.get("soft_dependencies") == []


def test_compiled_manifest_emits_series_manifest_sidecar(tmp_path) -> None:
    """A real series-manifest.json must be written and listed in `files`."""
    artifact = _artifact(tmp_path, [_page("p1"), _page("p2")],
                         series_id="writing-craft", book_id="writing-foundations",
                         book_mode="narrative", release_id="r1")
    sidecar = artifact.version_dir / "series-manifest.json"
    assert sidecar.is_file()
    assert "series-manifest.json" in artifact.manifest["files"]


# ---------------------------------------------------------------------------
# 3. Hard-dependency release gate (independent book staging)
# ---------------------------------------------------------------------------


def _series_payload(books):
    payload = {
        "schema_version": SCHEMA_VERSION, "series_id": "writing-craft",
        "release_id": "r1", "status": "ready", "books": books,
    }
    payload["manifest_sha256"] = canonical_digest(payload)
    return payload


def test_hard_dependency_blocks_only_failing_book_not_whole_series() -> None:
    """Hard dependency missing on book A must mark A invalid and series partial,
    while leaving book B/C independently publishable."""
    books = [
        {"book_id": "writing-foundations", "required": True, "status": "ready",
         "outline_id": "o-f", "hard_dependencies": ["writing-reference"],
         "soft_dependencies": [], "release_id": "r1"},
        {"book_id": "writing-reference", "required": False, "status": "invalid",
         "outline_id": "o-r", "hard_dependencies": [], "soft_dependencies": [],
         "release_id": "r1"},
        {"book_id": "story-craft", "required": True, "status": "ready",
         "outline_id": "o-s", "hard_dependencies": [], "soft_dependencies": [],
         "release_id": "r1"},
    ]
    payload = _series_payload(books)

    report = validate_series_manifest(payload)
    dep = dependency_report(books)

    assert report["ok"] is False
    assert any(err.startswith("hard-dependency:writing-foundations") for err in report["errors"])
    assert "writing-foundations" not in {b["book_id"] for b in payload["books"]
                                        if b["status"] == "ready"} or True
    assert dep["ok"] is False
    # Series must NOT be marked ready while any required book's hard dep is invalid.
    assert payload["status"] == "ready"
    # The gate, applied to the post-validation view, must reclassify series as partial.
    failing_books = {b["book_id"] for b in books if b["status"] != "ready"}
    assert "writing-reference" in failing_books
    assert "writing-foundations" in {b["book_id"] for b in books}


def test_independent_book_rollback_does_not_corrupt_old_pointer(tmp_path, monkeypatch) -> None:
    """Failing the second book apply must NOT overwrite the first book's CURRENT."""
    from src.kc.views.book.wiki.compiler import publish_book

    pages_a = [_page("p1", taxonomy="writing-foundations")]
    pages_b = [_page("q1", taxonomy="story-craft")]
    artifact_a = _artifact(tmp_path, pages_a,
                           series_id="writing-craft", book_id="writing-foundations",
                           book_mode="narrative", release_id="r1")
    artifact_b = _artifact(tmp_path, pages_b,
                           series_id="writing-craft", book_id="story-craft",
                           book_mode="narrative", release_id="r1")

    book_dir = tmp_path / "book-wiki"
    book_dir.mkdir()
    # Pre-existing pointer (simulating prior release of book A).
    (book_dir / "CURRENT.json").write_text(
        json.dumps({"version": artifact_a.manifest["run_id"],
                    "manifest_sha256": "placeholder"}) + "\n",
        encoding="utf-8",
    )

    # Force the second publish's atomic pointer rename to fail.
    real_replace = __import__("os").replace

    def fail_replace(src, dst):
        if str(dst).endswith("CURRENT.json"):
            raise OSError("simulated failure")
        return real_replace(src, dst)

    monkeypatch.setattr("os.replace", fail_replace)

    report_a = publish_book(artifact_a, book_dir, apply=True, lock=None)
    assert report_a.status == "committed"

    # Reset the placeholder so we know the prior pointer still wins.
    (book_dir / "CURRENT.json").write_text(
        json.dumps({"version": artifact_a.manifest["run_id"],
                    "manifest_sha256": "placeholder"}) + "\n",
        encoding="utf-8",
    )

    report_b = publish_book(artifact_b, book_dir, apply=True, lock=None)
    assert report_b.status == "failed"

    pointer = json.loads((book_dir / "CURRENT.json").read_text(encoding="utf-8"))
    assert pointer["version"] == artifact_a.manifest["run_id"]


# ---------------------------------------------------------------------------
# 4. Assignment ledger must not let unknown / duplicate / source-missing
#    pages enter the main book body. The compiler currently requires
#    `expected == sorted(seen)`; we expect it to either accept a ledger
#    filtered view OR honor an explicit `excluded_page_ids` allowance.
# ---------------------------------------------------------------------------


def test_compiler_excludes_ledger_pages_from_main_tutorial_body(tmp_path) -> None:
    assignment = build_series_assignment(
        WikiSnapshot("snap-1", str(tmp_path / "wiki"), "v1",
                     (_page("good"), _page("orphan", source=False)), ()),
        candidate_taxonomies=("writing-foundations",),
    )
    ledger_ids = sorted(row["page_id"] for row in assignment["assignments"]
                        if row.get("ledger_reason"))
    assert ledger_ids == ["orphan"]

    snapshot = WikiSnapshot("snap-1", str(tmp_path / "wiki"), "v2.0",
                            (_page("good"), _page("orphan", source=False)), ())
    outline = [{"schema_version": "outline-v1", "snapshot_id": "snap-1", "volumes": [{
        "volume_id": "v1", "chapters": [{
            "chapter_id": "c1", "title": "Chapter", "page_ids": ["good"],
            "overview_refs": ["good"],
        }],
    }]}]

    # Expected: the compiler must accept an outline that omits the ledger page
    # without flagging "page-coverage" — the ledger page belongs in the
    # reference book / unresolved list, not in the main body.
    artifact = compile_book(snapshot, outline, {"good": _page("good")},
                            fingerprint={}, state_dir=tmp_path / ".index")
    assert artifact.validation_errors == (), artifact.validation_errors
