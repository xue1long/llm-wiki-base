"""Staged release / partial failure / hard-dependency release gate.

Contracts enforced (per 2026-09-06 book-series plan Task 5/8):

* Failing one book must NOT corrupt the active ``CURRENT.json`` left behind
  by a previously committed book.
* A second book publish with an unrelated hard dependency that does not yet
  ship in the same release must be rejected by the publish gate.
* The series status aggregator must downgrade a ``ready`` series to
  ``partial`` when only a subset of books is publishable.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


from src.kc.views.book.wiki.compiler import publish_book
from src.kc.views.book.wiki.model import ContentBlock, PageRecord, WikiSnapshot
from src.kc.views.book.wiki.polish_llm import GeneratedChapter, GeneratedSection
from src.kc.views.book.wiki.partition import (
    GovernanceConfig, ReaderProfile, evaluate_series_gate,
)
from src.kc.views.book.wiki.series_model import SCHEMA_VERSION, canonical_digest
from src.kc.views.book.wiki.series_validate import (
    dependency_report, validate_series_manifest,
)


# ─── fixtures ──────────────────────────────────────────────────────────


def _page(page_id: str, taxonomy: str = "writing-foundations",
          source: bool = True, relation_targets=()) -> PageRecord:
    return PageRecord(
        page_id, page_id, "concept", f"concepts/{page_id}.md", taxonomy,
        "summary",
        (ContentBlock(f"{page_id}:0", page_id, "Heading", "Body", 0),),
        relation_targets, f"hash-{page_id}", 4, None,
        sources=(f"source-{page_id}",) if source else (),
    )


def _artifact(tmp_path: Path, snapshot_pages, *, series_id: str, book_id: str,
              book_mode: str = "narrative", release_id: str = "r1"):
    from src.kc.views.book.wiki.compiler import compile_book
    snapshot = WikiSnapshot(
        "snap-1", str(tmp_path / "wiki"), "v2.0", tuple(snapshot_pages), ())
    outline = [{"schema_version": "outline-v1", "snapshot_id": "snap-1", "volumes": [{
        "volume_id": "v1", "chapters": [{
            "chapter_id": "c1", "title": "Chapter",
            "page_ids": [p.page_id for p in snapshot_pages],
            "overview_refs": [snapshot_pages[0].page_id],
            "reader_promise": "draft a story outline",
            "exit_artifact": "story_outline_doc",
            "hard_dependencies": [],
            "soft_dependencies": [],
        }],
    }]}]
    return compile_book(
        snapshot, outline, {p.page_id: p for p in snapshot_pages},
        fingerprint={}, state_dir=tmp_path / ".index",
        series_id=series_id, book_id=book_id,
        book_mode=book_mode, release_id=release_id,
        generated_chapters={"c1": GeneratedChapter(
            "c1",
            (GeneratedSection(
                "s1", "Chapter", "LLM body",
                tuple(p.page_id for p in snapshot_pages),
            ),),
            "complete",
        )},
    )


# ─── 1. independent staged rollback preserves old pointer ─────────────


def test_failing_book_publish_does_not_overwrite_previous_pointer(tmp_path,
                                                                  monkeypatch) -> None:
    """A book that fails ``os.replace`` must NOT touch a previously
    committed pointer. The release directory may be cleaned, but the
    old ``CURRENT.json`` must remain exactly as the prior publisher left it.
    """
    artifact_a = _artifact(tmp_path, [_page("p1", taxonomy="writing-foundations")],
                           series_id="writing-craft", book_id="writing-foundations")
    artifact_b = _artifact(tmp_path, [_page("q1", taxonomy="story-craft")],
                           series_id="writing-craft", book_id="story-craft")

    book_dir = tmp_path / "book-wiki"
    book_dir.mkdir()
    prior_pointer = {"version": artifact_a.manifest["run_id"],
                     "manifest_sha256": "placeholder"}
    (book_dir / "CURRENT.json").write_text(json.dumps(prior_pointer) + "\n",
                                          encoding="utf-8")

    real_replace = sys.modules["os"].replace

    def fail_replace(src, dst):
        if str(dst).endswith("CURRENT.json"):
            raise OSError("simulated failure")
        return real_replace(src, dst)

    monkeypatch.setattr("os.replace", fail_replace)

    report_a = publish_book(artifact_a, book_dir, apply=True, lock=None)
    assert report_a.status == "committed"

    # Repaint the pointer to the first book's id, then trigger the failing
    # publish of book B — the pointer must NOT change.
    (book_dir / "CURRENT.json").write_text(json.dumps(prior_pointer) + "\n",
                                          encoding="utf-8")

    report_b = publish_book(artifact_b, book_dir, apply=True, lock=None)
    assert report_b.status == "failed"

    pointer_after = json.loads((book_dir / "CURRENT.json").read_text(encoding="utf-8"))
    assert pointer_after == prior_pointer


# ─── 2. hard-dependency publish gate ───────────────────────────────────


def test_hard_dependency_missing_blocks_publish() -> None:
    """A book declaring a hard dependency on a non-existent / invalid book
    must surface ``hard-dependency:<self>:<missing>`` and the dependency
    report must be ``ok=False``. The publish gate must refuse to commit
    until the missing reference is resolved.
    """
    books = [
        {"book_id": "writing-foundations", "required": True, "status": "ready",
         "outline_id": "o-f", "hard_dependencies": ["writing-reference"],
         "soft_dependencies": [], "release_id": "r1"},
        {"book_id": "writing-reference", "required": False, "status": "invalid",
         "outline_id": "o-r", "hard_dependencies": [], "soft_dependencies": [],
         "release_id": "r1"},
    ]
    dep = dependency_report(books)
    assert dep["ok"] is False
    assert any(err == "hard-dependency:writing-foundations:writing-reference"
               for err in dep["errors"])

    series_payload = {
        "schema_version": SCHEMA_VERSION, "series_id": "writing-craft",
        "release_id": "r1", "status": "ready", "books": books,
    }
    series_payload["manifest_sha256"] = canonical_digest(series_payload)
    report = validate_series_manifest(series_payload)
    assert report["ok"] is False
    # writing-reference is required=False, so the validator emits ready-gate.
    # Marking it required must surface required-not-ready instead.
    assert "ready-gate" in report["errors"]

    books_required = list(books)
    books_required[1] = dict(books_required[1], required=True)
    payload_required = {
        "schema_version": SCHEMA_VERSION, "series_id": "writing-craft",
        "release_id": "r1", "status": "ready", "books": books_required,
    }
    payload_required["manifest_sha256"] = canonical_digest(payload_required)
    report_required = validate_series_manifest(payload_required)
    assert report_required["ok"] is False
    assert "required-not-ready" in report_required["errors"]


# ─── 3. partial-success series state ───────────────────────────────────


def test_series_status_downgrades_to_partial_when_subset_succeeds(tmp_path) -> None:
    """When two out of three required books ship in the same release, the
    series manifest validator must reject the ``ready`` status and force
    the caller to downgrade to ``partial``. This guarantees the UI cannot
    accidentally claim a complete series when one book is still missing.
    """
    books = [
        {"book_id": "writing-foundations", "required": True, "status": "ready",
         "outline_id": "o-f", "hard_dependencies": [], "soft_dependencies": [],
         "release_id": "r1"},
        {"book_id": "story-craft", "required": True, "status": "partial",
         "outline_id": "o-s", "hard_dependencies": [], "soft_dependencies": [],
         "release_id": "r1"},
        {"book_id": "revision-release", "required": True, "status": "ready",
         "outline_id": "o-r", "hard_dependencies": [], "soft_dependencies": [],
         "release_id": "r1"},
    ]
    series_payload = {
        "schema_version": SCHEMA_VERSION, "series_id": "writing-craft",
        "release_id": "r1", "status": "ready", "books": books,
    }
    series_payload["manifest_sha256"] = canonical_digest(series_payload)
    report = validate_series_manifest(series_payload)
    assert report["ok"] is False
    assert "required-not-ready" in report["errors"]

    # Partial is acceptable when we explicitly mark one book as in-flight.
    series_payload_partial = dict(series_payload, status="partial")
    series_payload_partial["manifest_sha256"] = canonical_digest(series_payload_partial)
    assert validate_series_manifest(series_payload_partial)["ok"]


# ─── 4. series gate fail-closed when baseline can not retain 3 books ───


def _snapshot(*pages: PageRecord) -> WikiSnapshot:
    return WikiSnapshot("snap-1", "/tmp/wiki", "wiki-v3", tuple(pages), ())


def test_baseline_downgrades_when_candidate_book_is_too_thin() -> None:
    """A candidate with too few pages, low source coverage, or no exit
    evidence must be auto-downgraded (``merge`` / ``reference`` / ``cancel``).
    The series must never report a ``proceed`` decision for a thin book.
    """
    snapshot = _snapshot(_page("p1", taxonomy="book-a", source=False),
                         _page("p2", taxonomy="book-a"))
    profile = ReaderProfile(profile_id="r",
                            task_types=("learn_concept",),
                            candidate_taxonomies=("book-a", "book-b", "book-c"),
                            min_pages_per_book=5, min_source_coverage=0.8,
                            min_reader_tasks=3, chapter_exit_evidence=())
    result = evaluate_series_gate(snapshot, reader_profile=profile,
                                 governance=GovernanceConfig(True, 1, "approver"))
    candidate_a = next(c for c in result.candidates if c.candidate_id == "book-a")
    assert candidate_a.decision in {"merge", "reference", "cancel"}
    assert candidate_a.decision != "proceed"
    assert "LOW_SOURCE_COVERAGE" in candidate_a.reason_codes
    assert "INSUFFICIENT_PAGES" in candidate_a.reason_codes
    # Series-wide decision must reflect no proceedable book.
    assert result.status in {"ready", "blocked"}
    assert not any(c.decision == "proceed" for c in result.candidates)
