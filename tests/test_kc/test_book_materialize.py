"""Tests for the Book snapshot materializer (book-build runtime wiring, Task 1).

The materializer bridges a REAL project's KC persistence (``.index/kc/``) and
the Book view contract. Without it, ``rebuild_book`` could only be fed
hand-written JSON snapshots — which is why "generate book" was never a
reachable runtime path.

Scope (Task 1 — pure read layer, no CLI / no HTTP):

    * pure read of ``<project_root>/.index/kc/bundles/**`` + ``publication_state.json``
    * one KnowledgeUnit per ``provenance.source_path`` (decision D-1)
    * ``unit_type="principle"`` + ``derived=True`` (decision D-2)
    * deterministic ids so repeated runs are idempotent
    * NO writes to the project tree

Non-goals (later tasks): CLI wiring (Task 2), HTTP wiring (Task 3).
"""
from __future__ import annotations

import json
from pathlib import Path


from src.kc.domain.knowledge_unit import KnowledgeUnit
from src.kc.integrity.orchestrator import IntegrityGate
from src.kc.views.book import Book, Chapter
from src.kc.views.book.materialize import (
    BookSnapshot,
    BookSnapshotStats,
    materialize_book_snapshot,
)


# ─── Fixture builders ──────────────────────────────────────────────────


def _claim(
    object_id: str,
    *,
    source_path: str,
    title: str = "claim title",
    content: str = "claim content",
    obj_type: str = "claim",
    confidence: float = 1.0,
    lifecycle: str = "processing",
) -> dict:
    return {
        "id": object_id,
        "type": obj_type,
        "title": title,
        "content": content,
        "lifecycle": lifecycle,
        "confidence": confidence,
        "provenance": {
            "source_path": source_path,
            "source_paths": [source_path],
            "page": None,
            "quote": "raw quote",
            "ingested_at": 0,
            "ingestor_version": "legacy-text-v1",
        },
        "grade": "B",
        "heat": 50,
        "relations": [],
        "versions": [],
        "created_at": 0,
        "updated_at": 0,
        "custom_type": "",
        "valid_from": None,
        "valid_to": None,
        "ku_id": None,
    }


def _evidence(
    evidence_id: str,
    *,
    supports: list[str],
    document_id: str = "doc_test",
) -> dict:
    return {
        "evidence_id": evidence_id,
        "document_id": document_id,
        "block_id": f"block_{evidence_id}",
        "quote": "evidence quote",
        "quote_hash": "0" * 64,
        "supports": list(supports),
        "confidence": 0.0,
        "status": "candidate",
        "evidence_type": "direct_quote",
        "structured_provenance": None,
        "computation_provenance": None,
    }


def _write_bundle(
    kc_root: Path,
    bundle_key: str,
    *,
    source_path: str,
    claims: list[dict],
    evidences: list[dict] | None = None,
) -> Path:
    bundle_dir = kc_root / "bundles" / bundle_key
    (bundle_dir / "objects").mkdir(parents=True, exist_ok=True)
    if evidences is not None:
        (bundle_dir / "evidence").mkdir(parents=True, exist_ok=True)
    manifest = {
        "bundle_key": bundle_key,
        "candidate_id": f"cand_{bundle_key[:8]}",
        "document_id": f"doc_{bundle_key[:8]}",
        "source_path": source_path,
        "object_ids": [c["id"] for c in claims],
        "status": "staged",
    }
    (bundle_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for claim in claims:
        (bundle_dir / "objects" / f"{claim['id']}.json").write_text(
            json.dumps(claim, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    for ev in evidences or []:
        (bundle_dir / "evidence" / f"{ev['evidence_id']}.json").write_text(
            json.dumps(ev, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return bundle_dir


def _make_project(
    root: Path,
    *,
    bundles: list[tuple[str, str, list[dict], list[dict] | None]],
    publication_version: int | None = 3,
) -> Path:
    """Materialize a fake project with ``.index/kc`` persistence."""
    kc_root = root / ".index" / "kc"
    kc_root.mkdir(parents=True, exist_ok=True)
    for key, source_path, claims, evidences in bundles:
        _write_bundle(kc_root, key, source_path=source_path, claims=claims, evidences=evidences)
    if publication_version is not None:
        (kc_root / "publication_state.json").write_text(
            json.dumps({"current_version": publication_version, "active_batches": []}),
            encoding="utf-8",
        )
    return root


# ─── Empty / missing persistence ───────────────────────────────────────


def test_materialize_missing_kc_root_returns_empty_snapshot(tmp_path: Path) -> None:
    snapshot = materialize_book_snapshot(tmp_path)
    assert isinstance(snapshot, BookSnapshot)
    assert snapshot.chapters == ()
    assert snapshot.is_empty is True
    assert snapshot.stats.claim_count == 0
    assert snapshot.stats.knowledge_unit_count == 0
    assert "kc_root:missing" in snapshot.warning_codes


def test_materialize_empty_bundles_dir_returns_empty_snapshot(tmp_path: Path) -> None:
    kc_root = tmp_path / ".index" / "kc" / "bundles"
    kc_root.mkdir(parents=True)
    snapshot = materialize_book_snapshot(tmp_path)
    assert snapshot.is_empty is True
    assert snapshot.warning_codes == ()


def test_materialize_missing_publication_state_defaults_to_zero(tmp_path: Path) -> None:
    _make_project(
        tmp_path,
        bundles=[("bk1", "raw/sources/a.md", [_claim("c1", source_path="raw/sources/a.md")], None)],
        publication_version=None,
    )
    snapshot = materialize_book_snapshot(tmp_path)
    assert snapshot.publication_version == 0


# ─── Grouping (decision D-1) ───────────────────────────────────────────


def test_materialize_groups_claims_by_source_path(tmp_path: Path) -> None:
    _make_project(
        tmp_path,
        bundles=[
            (
                "bk1",
                "raw/sources/a.md",
                [_claim("c1", source_path="raw/sources/a.md"),
                 _claim("c2", source_path="raw/sources/a.md")],
                None,
            ),
            (
                "bk2",
                "raw/sources/b.md",
                [_claim("c3", source_path="raw/sources/b.md")],
                None,
            ),
        ],
    )
    snapshot = materialize_book_snapshot(tmp_path)

    assert snapshot.stats.claim_count == 3
    assert snapshot.stats.knowledge_unit_count == 2
    assert snapshot.stats.chapter_count == 2
    assert len(snapshot.chapters) == 2
    # One KU per source_path; the 2 claims of a.md collapse into one KU.
    ku_sizes = sorted(len(ch.source_knowledge_unit_ids) for ch in snapshot.chapters)
    assert ku_sizes == [1, 1]


def test_materialize_ku_claim_ids_are_sorted_and_complete(tmp_path: Path) -> None:
    _make_project(
        tmp_path,
        bundles=[
            (
                "bk1",
                "raw/sources/a.md",
                [_claim("c2", source_path="raw/sources/a.md"),
                 _claim("c1", source_path="raw/sources/a.md"),
                 _claim("c3", source_path="raw/sources/a.md")],
                None,
            )
        ],
    )
    snapshot = materialize_book_snapshot(tmp_path)
    chapter = snapshot.chapters[0]
    ku = snapshot.core_view.get_ku(chapter.source_knowledge_unit_ids[0])
    assert ku is not None
    assert ku.claim_ids == ("c1", "c2", "c3")


def test_materialize_skips_non_claim_objects(tmp_path: Path) -> None:
    _make_project(
        tmp_path,
        bundles=[
            (
                "bk1",
                "raw/sources/a.md",
                [_claim("c1", source_path="raw/sources/a.md"),
                 _claim("e1", source_path="raw/sources/a.md", obj_type="entity"),
                 _claim("f1", source_path="raw/sources/a.md", obj_type="structured_fact")],
                None,
            )
        ],
    )
    snapshot = materialize_book_snapshot(tmp_path)
    assert snapshot.stats.claim_count == 1
    assert snapshot.stats.skipped_object_count == 2


def test_materialize_uses_source_paths_fallback(tmp_path: Path) -> None:
    """Claims whose ``source_path`` is null fall back to ``source_paths[0]``."""
    claim = _claim("c1", source_path="raw/sources/a.md")
    claim["provenance"]["source_path"] = None
    _make_project(tmp_path, bundles=[("bk1", "raw/sources/a.md", [claim], None)])

    snapshot = materialize_book_snapshot(tmp_path)
    assert snapshot.stats.knowledge_unit_count == 1
    assert snapshot.stats.source_paths == ("raw/sources/a.md",)


# ─── KU field derivation (decision D-2) ────────────────────────────────


def test_materialize_ku_uses_principle_unit_type(tmp_path: Path) -> None:
    _make_project(
        tmp_path,
        bundles=[("bk1", "raw/sources/a.md", [_claim("c1", source_path="raw/sources/a.md")], None)],
    )
    snapshot = materialize_book_snapshot(tmp_path)
    ku = snapshot.core_view.get_ku(snapshot.chapters[0].source_knowledge_unit_ids[0])
    assert isinstance(ku, KnowledgeUnit)
    assert ku.unit_type == "principle"          # D-2
    assert ku.knowledge_mode == "observed"      # backed by raw quotes


def test_materialize_marks_units_as_derived(tmp_path: Path) -> None:
    """D-2: no unit_type signal exists in the data — the snapshot must say so."""
    _make_project(
        tmp_path,
        bundles=[("bk1", "raw/sources/a.md", [_claim("c1", source_path="raw/sources/a.md")], None)],
    )
    snapshot = materialize_book_snapshot(tmp_path)
    assert snapshot.derived is True
    assert "derived_unit_type:principle" in snapshot.warning_codes


def test_materialize_ku_does_not_invent_question_content(tmp_path: Path) -> None:
    """D-2 / 不编造: the question is a source-scoped template, not fabricated content."""
    _make_project(
        tmp_path,
        bundles=[("bk1", "raw/sources/a.md", [_claim("c1", source_path="raw/sources/a.md")], None)],
    )
    snapshot = materialize_book_snapshot(tmp_path)
    ku = snapshot.core_view.get_ku(snapshot.chapters[0].source_knowledge_unit_ids[0])
    assert ku is not None
    assert "raw/sources/a.md" in ku.question
    assert ku.title == "a"


def test_materialize_stable_key_follows_contract(tmp_path: Path) -> None:
    _make_project(
        tmp_path,
        bundles=[("bk1", "raw/sources/a.md", [_claim("c1", source_path="raw/sources/a.md")], None)],
    )
    snapshot = materialize_book_snapshot(tmp_path)
    chapter = snapshot.chapters[0]
    ku = snapshot.core_view.get_ku(chapter.source_knowledge_unit_ids[0])
    assert ku is not None
    assert chapter.stable_key == f"{ku.concept_id}::principle"


# ─── Determinism / idempotency ─────────────────────────────────────────


def test_materialize_is_deterministic(tmp_path: Path) -> None:
    _make_project(
        tmp_path,
        bundles=[
            ("bk1", "raw/sources/a.md", [_claim("c1", source_path="raw/sources/a.md")], None),
            ("bk2", "raw/sources/b.md", [_claim("c2", source_path="raw/sources/b.md")], None),
        ],
    )
    first = materialize_book_snapshot(tmp_path)
    second = materialize_book_snapshot(tmp_path)

    assert first.book.id == second.book.id
    assert [c.id for c in first.chapters] == [c.id for c in second.chapters]
    assert [c.stable_key for c in first.chapters] == [c.stable_key for c in second.chapters]
    assert first.ku_evidence_map == second.ku_evidence_map


def test_materialize_chapter_ids_match_contract_shape(tmp_path: Path) -> None:
    """Ids keep the ``<prefix>_<hash8>_<slug>`` shape (uuid4 replaced by a
    content hash so rebuild output filenames are stable)."""
    _make_project(
        tmp_path,
        bundles=[("bk1", "raw/sources/a.md", [_claim("c1", source_path="raw/sources/a.md")], None)],
    )
    snapshot = materialize_book_snapshot(tmp_path)
    chapter = snapshot.chapters[0]
    prefix, hash8, slug = chapter.id.split("_", 2)
    assert prefix == "ch"
    assert len(hash8) == 8
    int(hash8, 16)  # hex-parseable
    assert slug
    assert snapshot.book.id.startswith("book_")


def test_materialize_chapters_are_ordered_by_source_path(tmp_path: Path) -> None:
    _make_project(
        tmp_path,
        bundles=[
            ("bkz", "raw/sources/z.md", [_claim("c3", source_path="raw/sources/z.md")], None),
            ("bka", "raw/sources/a.md", [_claim("c1", source_path="raw/sources/a.md")], None),
            ("bkm", "raw/sources/m.md", [_claim("c2", source_path="raw/sources/m.md")], None),
        ],
    )
    snapshot = materialize_book_snapshot(tmp_path)
    assert snapshot.stats.source_paths == (
        "raw/sources/a.md",
        "raw/sources/m.md",
        "raw/sources/z.md",
    )
    assert [c.order for c in snapshot.chapters] == [0, 1, 2]
    assert snapshot.book.chapter_ids == [c.id for c in snapshot.chapters]


# ─── Evidence wiring ───────────────────────────────────────────────────


def test_materialize_builds_ku_evidence_map(tmp_path: Path) -> None:
    _make_project(
        tmp_path,
        bundles=[
            (
                "bk1",
                "raw/sources/a.md",
                [_claim("c1", source_path="raw/sources/a.md"),
                 _claim("c2", source_path="raw/sources/a.md")],
                [_evidence("ev1", supports=["c1"]), _evidence("ev2", supports=["c2", "c1"])],
            )
        ],
    )
    snapshot = materialize_book_snapshot(tmp_path)
    chapter = snapshot.chapters[0]
    ku_id = chapter.source_knowledge_unit_ids[0]

    assert sorted(snapshot.ku_evidence_map[ku_id]) == ["ev1", "ev2"]
    assert snapshot.core_view.ku_evidence_ids(ku_id) == snapshot.ku_evidence_map[ku_id]


def test_materialize_splits_evidence_per_source(tmp_path: Path) -> None:
    _make_project(
        tmp_path,
        bundles=[
            ("bk1", "raw/sources/a.md",
             [_claim("c1", source_path="raw/sources/a.md")],
             [_evidence("ev1", supports=["c1"])]),
            ("bk2", "raw/sources/b.md",
             [_claim("c2", source_path="raw/sources/b.md")],
             [_evidence("ev2", supports=["c2"])]),
        ],
    )
    snapshot = materialize_book_snapshot(tmp_path)
    by_ku = {ch.source_knowledge_unit_ids[0]: ch for ch in snapshot.chapters}
    ku_a = [k for k in by_ku if "a.md" in snapshot.core_view.get_ku(k).concept_id][0]
    ku_b = [k for k in by_ku if "b.md" in snapshot.core_view.get_ku(k).concept_id][0]
    assert snapshot.ku_evidence_map[ku_a] == ("ev1",)
    assert snapshot.ku_evidence_map[ku_b] == ("ev2",)


def test_materialize_tolerates_missing_evidence(tmp_path: Path) -> None:
    _make_project(
        tmp_path,
        bundles=[("bk1", "raw/sources/a.md", [_claim("c1", source_path="raw/sources/a.md")], [])],
    )
    snapshot = materialize_book_snapshot(tmp_path)
    ku_id = snapshot.chapters[0].source_knowledge_unit_ids[0]
    assert snapshot.ku_evidence_map[ku_id] == ()


def test_materialize_evidence_is_resolvable_from_core_view(tmp_path: Path) -> None:
    _make_project(
        tmp_path,
        bundles=[
            ("bk1", "raw/sources/a.md",
             [_claim("c1", source_path="raw/sources/a.md")],
             [_evidence("ev1", supports=["c1"])])
        ],
    )
    snapshot = materialize_book_snapshot(tmp_path)
    evidence = snapshot.core_view.get_evidence("ev1")
    assert evidence is not None
    assert evidence.evidence_id == "ev1"
    assert evidence.evidence_type == "direct_quote"


# ─── Publication version + purity ──────────────────────────────────────


def test_materialize_reads_publication_version(tmp_path: Path) -> None:
    _make_project(
        tmp_path,
        bundles=[("bk1", "raw/sources/a.md", [_claim("c1", source_path="raw/sources/a.md")], None)],
        publication_version=7,
    )
    snapshot = materialize_book_snapshot(tmp_path)
    assert snapshot.publication_version == 7
    assert snapshot.core_view.current_publication_version() == 7


def test_materialize_does_not_write_to_project(tmp_path: Path) -> None:
    _make_project(
        tmp_path,
        bundles=[("bk1", "raw/sources/a.md", [_claim("c1", source_path="raw/sources/a.md")], None)],
    )
    before = {str(p.relative_to(tmp_path)): p.stat().st_mtime_ns for p in tmp_path.rglob("*")}
    materialize_book_snapshot(tmp_path)
    after = {str(p.relative_to(tmp_path)): p.stat().st_mtime_ns for p in tmp_path.rglob("*")}
    assert before == after


def test_materialize_accepts_string_path(tmp_path: Path) -> None:
    _make_project(
        tmp_path,
        bundles=[("bk1", "raw/sources/a.md", [_claim("c1", source_path="raw/sources/a.md")], None)],
    )
    snapshot = materialize_book_snapshot(str(tmp_path))
    assert snapshot.stats.chapter_count == 1


# ─── Downstream contract: the snapshot must feed rebuild_book ──────────


def test_materialized_snapshot_resolves_kus_for_chapter(tmp_path: Path) -> None:
    _make_project(
        tmp_path,
        bundles=[
            ("bk1", "raw/sources/a.md", [_claim("c1", source_path="raw/sources/a.md")], None),
            ("bk2", "raw/sources/b.md", [_claim("c2", source_path="raw/sources/b.md")], None),
        ],
    )
    snapshot = materialize_book_snapshot(tmp_path)
    for chapter in snapshot.chapters:
        kus = snapshot.core_view.kus_for_chapter(chapter)   # must not raise
        assert len(kus) == 1
        assert kus[0].ku_id == chapter.source_knowledge_unit_ids[0]


def test_materialized_snapshot_passes_integrity_gates(tmp_path: Path) -> None:
    """Guard rail: if derived KUs were gate-blocked, rebuild would always fail."""
    _make_project(
        tmp_path,
        bundles=[
            ("bk1", "raw/sources/a.md",
             [_claim("c1", source_path="raw/sources/a.md")],
             [_evidence("ev1", supports=["c1"])])
        ],
    )
    snapshot = materialize_book_snapshot(tmp_path)
    gate = IntegrityGate()
    for chapter in snapshot.chapters:
        for ku in snapshot.core_view.kus_for_chapter(chapter):
            report = gate.check(ku)
            assert report.blocked is False, report.get_blocking_reasons()


def test_materialized_snapshot_feeds_rebuild_dry_run(tmp_path: Path) -> None:
    from src.kc.views.book import rebuild_book

    _make_project(
        tmp_path,
        bundles=[
            ("bk1", "raw/sources/a.md",
             [_claim("c1", source_path="raw/sources/a.md")],
             [_evidence("ev1", supports=["c1"])]),
            ("bk2", "raw/sources/b.md",
             [_claim("c2", source_path="raw/sources/b.md")],
             [_evidence("ev2", supports=["c2"])]),
        ],
    )
    snapshot = materialize_book_snapshot(tmp_path)
    report = rebuild_book(
        snapshot.book,
        snapshot.chapters,
        snapshot.core_view,
        IntegrityGate(),
        apply=False,
    )
    assert report.status == "planned"
    assert report.not_evaluable is False
    assert len(report.rebuilt_chapter_ids) == 2
    assert report.failed_chapter_ids == ()


# ─── Stats surface ─────────────────────────────────────────────────────


def test_snapshot_stats_fields(tmp_path: Path) -> None:
    _make_project(
        tmp_path,
        bundles=[
            ("bk1", "raw/sources/a.md",
             [_claim("c1", source_path="raw/sources/a.md")],
             [_evidence("ev1", supports=["c1"])]),
        ],
    )
    snapshot = materialize_book_snapshot(tmp_path)
    assert isinstance(snapshot.stats, BookSnapshotStats)
    assert snapshot.stats.bundle_count == 1
    assert snapshot.stats.claim_count == 1
    assert snapshot.stats.evidence_count == 1
    assert snapshot.stats.knowledge_unit_count == 1
    assert snapshot.stats.chapter_count == 1
    assert snapshot.stats.source_paths == ("raw/sources/a.md",)


def test_snapshot_book_contract(tmp_path: Path) -> None:
    _make_project(
        tmp_path,
        bundles=[("bk1", "raw/sources/a.md", [_claim("c1", source_path="raw/sources/a.md")], None)],
    )
    snapshot = materialize_book_snapshot(tmp_path, book_title="My Book")
    assert isinstance(snapshot.book, Book)
    assert snapshot.book.title == "My Book"
    for chapter in snapshot.chapters:
        assert isinstance(chapter, Chapter)
        assert chapter.book_id == snapshot.book.id
