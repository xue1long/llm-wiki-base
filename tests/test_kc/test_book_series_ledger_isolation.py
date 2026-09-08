"""Ledger / compiler integration — ledger pages must not enter main body.

Contracts enforced (per 2026-09-06 book-series plan Task 2):

* When ``compile_book`` receives an outline that excludes ledger pages, the
  compiler must accept that view and not flag ``page-coverage``.
* The compiled manifest must record ``ledger_page_ids`` so downstream
  tooling can audit what was held back.
* Secondary topics (a page attached to multiple books) must surface as
  cross-references in the chapter body — they must not produce a second
  rendered chapter for the same page.
"""
from __future__ import annotations

from pathlib import Path


from src.kc.views.book.wiki.compiler import compile_book
from src.kc.views.book.wiki.model import ContentBlock, PageRecord, WikiSnapshot
from src.kc.views.book.wiki.partition import build_series_assignment


def _page(page_id: str, taxonomy: str = "writing-foundations",
          source: bool = True, relation_targets=(), digest: str | None = None) -> PageRecord:
    return PageRecord(
        page_id, page_id, "concept", f"concepts/{page_id}.md", taxonomy,
        "summary",
        (ContentBlock(f"{page_id}:0", page_id, "Heading", f"Body of {page_id}", 0),),
        relation_targets, digest or f"hash-{page_id}", 4, None,
        sources=(f"source-{page_id}",) if source else (),
    )


def _artifact(tmp_path: Path, pages, *, outline_page_ids,
              series_id: str | None = None, book_id: str | None = None,
              book_mode: str | None = None, release_id: str | None = None,
              page_map=None):
    snapshot = WikiSnapshot("snap-1", str(tmp_path / "wiki"), "v2.0", tuple(pages), ())
    outline = [{"schema_version": "outline-v1", "snapshot_id": "snap-1", "volumes": [{
        "volume_id": "v1", "chapters": [{
            "chapter_id": "c1", "title": "Chapter",
            "page_ids": list(outline_page_ids),
            "overview_refs": list(outline_page_ids[:1] or ["good"]),
        }],
    }]}]
    pm = page_map if page_map is not None else {p.page_id: p for p in pages}
    return compile_book(snapshot, outline, pm, fingerprint={},
                        state_dir=tmp_path / ".index",
                        series_id=series_id, book_id=book_id,
                        book_mode=book_mode, release_id=release_id)


# ─── 1. compile_book must accept an outline that omits ledger pages ────


def test_compile_book_accepts_outline_excluding_ledger_pages(tmp_path) -> None:
    """The compiler must not raise ``page-coverage`` when the caller
    hands in an outline that intentionally omits ledger pages. The
    ledger belongs in the reference book / unresolved list, not the
    main tutorial body.
    """
    pages = [_page("good"), _page("orphan", source=False)]
    assignment = build_series_assignment(
        WikiSnapshot("snap-1", str(tmp_path / "wiki"), "v1", tuple(pages), ()),
        candidate_taxonomies=("writing-foundations",),
    )
    ledger = sorted(row["page_id"] for row in assignment["assignments"]
                    if row.get("ledger_reason"))
    assert ledger == ["orphan"]

    artifact = _artifact(tmp_path, pages, outline_page_ids=["good"])
    assert artifact.validation_errors == (), artifact.validation_errors


# ─── 2. manifest must record ledger_page_ids for downstream auditing ───


def test_manifest_records_ledger_page_ids_for_held_back_pages(tmp_path) -> None:
    """``compile_book`` must surface ``ledger_page_ids`` in the manifest
    when ledger pages are excluded from the chapter outline. This gives
    downstream tooling and the publisher a stable audit signal.
    """
    pages = [_page("good"), _page("orphan", source=False)]
    artifact = _artifact(tmp_path, pages, outline_page_ids=["good"],
                         series_id="writing-craft", book_id="writing-foundations",
                         book_mode="narrative", release_id="r1")
    manifest = artifact.manifest
    ledger = manifest.get("ledger_page_ids") or manifest.get("ledger_pages") or []
    assert sorted(ledger) == ["orphan"], (
        "Expected ledger_page_ids=['orphan'] in the compiled manifest so "
        "downstream tooling can audit held-back pages. Got: "
        f"{manifest.get('ledger_page_ids')!r} / {manifest.get('ledger_pages')!r}"
    )


# ─── 3. secondary topics must not duplicate rendering ──────────────────


def test_secondary_topic_pages_do_not_render_twice(tmp_path) -> None:
    """A page attached to two books (secondary topic) must appear once in
    the main tutorial body and once as a cross-reference in the manifest.
    The compiler must NOT render the same page body twice.
    """
    pages = [
        _page("shared", taxonomy="writing-foundations",
              relation_targets=(("related", "unique-b"),)),
        _page("unique-a", taxonomy="writing-foundations"),
        _page("unique-b", taxonomy="story-craft"),
    ]
    artifact = _artifact(tmp_path, pages,
                         outline_page_ids=["shared", "unique-a"])
    # The chapter body should embed each page block_id at most once.
    body_files = [name for name in artifact.manifest["files"]
                  if name.endswith(".md") and "glossary" not in name and "index" not in name]
    assert body_files, "Expected at least one chapter body file"
    combined = "\n".join((artifact.version_dir / name).read_text(encoding="utf-8")
                         for name in body_files)
    # The page block for "shared" should appear once in the main body.
    assert combined.count("Body of shared") == 1, (
        f"shared page rendered {combined.count('Body of shared')} times; expected 1"
    )
    # Secondary topics should be surfaced in the manifest.
    secondaries = artifact.manifest.get("secondary_topic_page_ids") or []
    assert "shared" in secondaries, (
        "Expected shared page to be surfaced as a secondary topic in the "
        f"manifest; got {secondaries!r}"
    )
