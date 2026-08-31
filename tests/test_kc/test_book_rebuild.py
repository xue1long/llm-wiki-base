from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.kc.contracts.evidence import Evidence
from src.kc.domain.knowledge_unit import KnowledgeUnit
from src.kc.integrity.gates import Gate, GateVerdict
from src.kc.integrity.orchestrator import IntegrityGate
from src.kc.views.book.core_view import SimpleKnowledgeCoreView

try:
    import src.kc.views.book.rebuild as rebuild_mod
    from src.kc.views.book import (
        Book,
        BookRebuildReport,
        BookTemplate,
        Chapter,
        rebuild_book,
    )
except ImportError:  # pragma: no cover - red phase until Task 3 lands
    rebuild_mod = None  # type: ignore[assignment]
    Book = None  # type: ignore[assignment]
    BookRebuildReport = None  # type: ignore[assignment]
    BookTemplate = None  # type: ignore[assignment]
    Chapter = None  # type: ignore[assignment]
    rebuild_book = None  # type: ignore[assignment]


def _ku(
    *,
    ku_id: str,
    title: str,
    unit_type: str = "definition",
    knowledge_mode: str = "observed",
) -> KnowledgeUnit:
    return KnowledgeUnit(
        ku_id=ku_id,
        concept_id=f"concept-{ku_id}",
        question=f"What is {title}?",
        title=title,
        unit_type=unit_type,  # type: ignore[arg-type]
        knowledge_mode=knowledge_mode,  # type: ignore[arg-type]
    )


def _evidence(evidence_id: str) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        document_id=f"doc-{evidence_id}",
        block_id=f"block-{evidence_id}",
        quote=f"quote for {evidence_id}",
        quote_hash=(evidence_id * 8)[:64],
        evidence_type="direct_quote",
    )


def _chapter(
    chapter_id: str,
    ku_id: str,
    order: int,
    *,
    publication_version: int = 0,
) -> Chapter:
    return Chapter(
        id=chapter_id,
        book_id="book-1",
        stable_key=f"stable-{chapter_id}",
        title=f"Chapter {order}",
        order=order,
        source_knowledge_unit_ids=[ku_id],
        publication_version=publication_version,
    )


def _fixture(
    *,
    publication_version: int = 7,
    broken_ku_id: str | None = None,
    missing_evidence_for: str | None = None,
) -> tuple[Book, tuple[Chapter, ...], SimpleKnowledgeCoreView]:
    kus = {
        "ku-1": _ku(ku_id="ku-1", title="one"),
        "ku-2": _ku(ku_id="ku-2", title="two", unit_type="mechanism"),
        "ku-3": _ku(ku_id="ku-3", title="three", unit_type="principle"),
    }
    chapters = (
        _chapter("ch-1", "ku-1", 1, publication_version=1),
        _chapter("ch-2", broken_ku_id or "ku-2", 2, publication_version=2),
        _chapter("ch-3", "ku-3", 3, publication_version=3),
    )
    book = Book(
        id="book-1",
        title="Book",
        template_id="default_v1",
        chapter_ids=[chapter.id for chapter in chapters],
        publication_version=999,
    )
    evidences = {
        "ev-1": _evidence("ev-1"),
        "ev-2": _evidence("ev-2"),
        "ev-3": _evidence("ev-3"),
    }
    ku_evidence_map = {
        "ku-1": ("ev-1",),
        "ku-2": ("ev-2",),
        "ku-3": ("ev-3",),
    }
    if missing_evidence_for is not None:
        ku_evidence_map[missing_evidence_for] = ("ev-missing",)
    return (
        book,
        chapters,
        SimpleKnowledgeCoreView(
            kus=kus,
            evidences=evidences,
            ku_evidence_map=ku_evidence_map,
            publication_version=publication_version,
        ),
    )


class _AlwaysBlockGate(Gate):
    name = "always_block"
    order = 99

    def check(self, obj: Any, context: dict | None = None) -> GateVerdict:
        return GateVerdict.block(["forced_block:test"])


class _AlwaysBlockIntegrityGate(IntegrityGate):
    def __init__(self) -> None:
        super().__init__()
        self._gates = (_AlwaysBlockGate(),)


class _ChangingPublicationCoreView(SimpleKnowledgeCoreView):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.version_reads = 0

    def current_publication_version(self) -> int:
        self.version_reads += 1
        return self.publication_version + self.version_reads - 1


def test_empty_book_returns_planned_not_evaluable_and_writes_nothing(tmp_path: Path) -> None:
    output_dir = tmp_path / "book"

    report = rebuild_book(
        Book(id="book-empty", title="Empty", template_id="default_v1", chapter_ids=[]),
        (),
        SimpleKnowledgeCoreView(publication_version=11),
        IntegrityGate(),
        output_dir=output_dir,
        apply=False,
    )

    assert isinstance(report, BookRebuildReport)
    assert report.status == "planned"
    assert report.book_id == "book-empty"
    assert report.publication_version == 11
    assert report.rebuilt_chapter_ids == ()
    assert report.failed_chapter_ids == ()
    assert report.reason_codes == ()
    assert report.rendered_hashes == {}
    assert report.not_evaluable is True
    assert not output_dir.exists()


def test_apply_true_rebuilds_all_chapters_and_writes_markdown_and_metadata(tmp_path: Path) -> None:
    book, chapters, core_view = _fixture(publication_version=7)
    output_dir = tmp_path / "book"
    keep_path = output_dir / "keep.md"
    output_dir.mkdir(parents=True)
    keep_path.write_text("keep", encoding="utf-8")

    report = rebuild_book(
        book,
        chapters,
        core_view,
        IntegrityGate(),
        output_dir=output_dir,
        apply=True,
    )

    assert report.status == "committed"
    assert report.publication_version == 7
    assert report.rebuilt_chapter_ids == ("ch-1", "ch-2", "ch-3")
    assert report.failed_chapter_ids == ()
    assert report.reason_codes == ()
    assert set(report.rendered_hashes) == {"ch-1", "ch-2", "ch-3"}
    assert keep_path.read_text(encoding="utf-8") == "keep"

    for chapter in chapters:
        markdown_path = output_dir / f"{chapter.id}.md"
        metadata_path = output_dir / f"{chapter.id}.json"
        assert markdown_path.exists()
        assert metadata_path.exists()
        assert f"publication_version: 7" in markdown_path.read_text(encoding="utf-8")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        assert metadata["book_id"] == book.id
        assert metadata["chapter_id"] == chapter.id
        assert metadata["publication_version"] == 7
        assert metadata["rendered_hash"] == report.rendered_hashes[chapter.id]


def test_target_subset_rebuilds_only_requested_chapters_and_preserves_unrelated_pages(tmp_path: Path) -> None:
    book, chapters, core_view = _fixture(
        publication_version=5,
        broken_ku_id="ku-missing-outside-target",
    )
    output_dir = tmp_path / "book"
    output_dir.mkdir(parents=True)
    untouched_md = output_dir / "ch-2.md"
    untouched_json = output_dir / "ch-2.json"
    untouched_md.write_text("old chapter 2", encoding="utf-8")
    untouched_json.write_text('{"chapter_id":"ch-2","rendered_hash":"old"}', encoding="utf-8")

    report = rebuild_book(
        book,
        chapters,
        core_view,
        IntegrityGate(),
        target_chapter_ids=("ch-1",),
        output_dir=output_dir,
        apply=True,
    )

    assert report.status == "committed"
    assert report.rebuilt_chapter_ids == ("ch-1",)
    assert report.failed_chapter_ids == ()
    assert set(report.rendered_hashes) == {"ch-1"}
    assert (output_dir / "ch-1.md").exists()
    assert untouched_md.read_text(encoding="utf-8") == "old chapter 2"
    assert untouched_json.read_text(encoding="utf-8") == '{"chapter_id":"ch-2","rendered_hash":"old"}'
    assert not (output_dir / "ch-3.md").exists()


def test_target_chapter_outside_book_is_rejected_and_existing_page_is_preserved(tmp_path: Path) -> None:
    book, chapters, core_view = _fixture(publication_version=5)
    foreign_chapter = Chapter(
        id="ch-foreign",
        book_id="book-other",
        stable_key="stable-ch-foreign",
        title="Foreign chapter",
        order=1,
        source_knowledge_unit_ids=["ku-1"],
    )
    output_dir = tmp_path / "book"
    output_dir.mkdir()
    foreign_path = output_dir / "ch-foreign.md"
    foreign_path.write_text("foreign old content", encoding="utf-8")

    report = rebuild_book(
        book,
        chapters + (foreign_chapter,),
        core_view,
        IntegrityGate(),
        target_chapter_ids=("ch-foreign",),
        output_dir=output_dir,
        apply=True,
    )

    assert report.status == "failed"
    assert report.failed_chapter_ids == ("ch-foreign",)
    assert report.reason_codes == ("chapter_resolution:not_in_book",)
    assert foreign_path.read_text(encoding="utf-8") == "foreign old content"


def test_report_publication_version_comes_from_core_view_not_book_or_chapter() -> None:
    book, chapters, core_view = _fixture(publication_version=19)

    report = rebuild_book(
        book,
        chapters,
        core_view,
        IntegrityGate(),
        apply=False,
    )

    assert report.status == "planned"
    assert report.publication_version == 19


def test_rebuild_uses_one_publication_version_snapshot_for_report_and_output(tmp_path: Path) -> None:
    book, chapters, core_view = _fixture(publication_version=7)
    changing_core_view = _ChangingPublicationCoreView(
        kus=core_view.kus,
        evidences=core_view.evidences,
        ku_evidence_map=core_view.ku_evidence_map,
        publication_version=7,
    )
    output_dir = tmp_path / "book"

    report = rebuild_book(
        book,
        chapters,
        changing_core_view,
        IntegrityGate(),
        output_dir=output_dir,
        apply=True,
    )

    assert report.status == "committed"
    assert report.publication_version == 7
    assert changing_core_view.version_reads == 1
    for chapter in chapters:
        assert "publication_version: 7" in (output_dir / f"{chapter.id}.md").read_text(encoding="utf-8")
        metadata = json.loads((output_dir / f"{chapter.id}.json").read_text(encoding="utf-8"))
        assert metadata["publication_version"] == 7


def test_missing_evidence_returns_failed_and_preserves_existing_files(tmp_path: Path) -> None:
    book, chapters, core_view = _fixture(
        publication_version=7,
        missing_evidence_for="ku-1",
    )
    output_dir = tmp_path / "book"
    output_dir.mkdir(parents=True)
    old_path = output_dir / "ch-1.md"
    old_path.write_text("old content", encoding="utf-8")

    report = rebuild_book(
        book,
        chapters,
        core_view,
        IntegrityGate(),
        output_dir=output_dir,
        apply=True,
    )

    assert report.status == "failed"
    assert report.failed_chapter_ids == ("ch-1",)
    assert any(code.startswith("evidence_unsupported:") for code in report.reason_codes)
    assert old_path.read_text(encoding="utf-8") == "old content"
    assert not (output_dir / "ch-1.json").exists()


def test_integrity_gate_block_returns_failed_and_preserves_existing_files(tmp_path: Path) -> None:
    book, chapters, core_view = _fixture(publication_version=7)
    output_dir = tmp_path / "book"
    output_dir.mkdir(parents=True)
    old_path = output_dir / "ch-1.md"
    old_path.write_text("still here", encoding="utf-8")

    report = rebuild_book(
        book,
        chapters,
        core_view,
        _AlwaysBlockIntegrityGate(),
        output_dir=output_dir,
        apply=True,
    )

    assert report.status == "failed"
    assert report.failed_chapter_ids == ("ch-1",)
    assert report.reason_codes == ("forced_block:test",)
    assert old_path.read_text(encoding="utf-8") == "still here"


def test_render_failure_returns_failed_and_preserves_existing_files(tmp_path: Path) -> None:
    book, chapters, core_view = _fixture(publication_version=7)
    output_dir = tmp_path / "book"
    output_dir.mkdir(parents=True)
    old_path = output_dir / "ch-1.md"
    old_path.write_text("old render", encoding="utf-8")

    def _explode(render: Any) -> str:
        raise RuntimeError("boom")

    template = BookTemplate(custom_renderers={"header": _explode})
    report = rebuild_book(
        book,
        chapters,
        core_view,
        IntegrityGate(),
        template=template,
        output_dir=output_dir,
        apply=True,
    )

    assert report.status == "failed"
    assert report.failed_chapter_ids == ("ch-1",)
    assert report.reason_codes == ("render_exception:RuntimeError",)
    assert old_path.read_text(encoding="utf-8") == "old render"


def test_apply_false_is_dry_run_and_does_not_write_files(tmp_path: Path) -> None:
    book, chapters, core_view = _fixture(publication_version=7)
    output_dir = tmp_path / "book"

    report = rebuild_book(
        book,
        chapters,
        core_view,
        IntegrityGate(),
        output_dir=output_dir,
        apply=False,
    )

    assert report.status == "planned"
    assert report.rebuilt_chapter_ids == ("ch-1", "ch-2", "ch-3")
    assert not output_dir.exists()


def test_staging_failure_returns_failed_and_preserves_existing_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    book, chapters, core_view = _fixture(publication_version=7)
    output_dir = tmp_path / "book"
    output_dir.mkdir(parents=True)
    old_md = output_dir / "ch-1.md"
    old_json = output_dir / "ch-1.json"
    old_md.write_text("old md", encoding="utf-8")
    old_json.write_text('{"rendered_hash":"old"}', encoding="utf-8")

    real_write_text = rebuild_mod._write_text

    def _fail_stage_write(path: Path, content: str) -> None:
        if ".rebuild-staging" in str(path.parent):
            raise OSError("disk full during staging")
        real_write_text(path, content)

    monkeypatch.setattr(rebuild_mod, "_write_text", _fail_stage_write)

    report = rebuild_book(
        book,
        chapters,
        core_view,
        IntegrityGate(),
        output_dir=output_dir,
        apply=True,
    )

    assert report.status == "failed"
    assert report.failed_chapter_ids == ("ch-1",)
    assert report.reason_codes == ("write_exception:OSError",)
    assert old_md.read_text(encoding="utf-8") == "old md"
    assert old_json.read_text(encoding="utf-8") == '{"rendered_hash":"old"}'


def test_commit_replace_failure_restores_files_already_replaced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    book, chapters, core_view = _fixture(publication_version=7)
    output_dir = tmp_path / "book"
    output_dir.mkdir()
    old_contents = {
        path.name: f"old {path.name}"
        for chapter_id in ("ch-1", "ch-2")
        for path in (output_dir / f"{chapter_id}.md", output_dir / f"{chapter_id}.json")
    }
    for filename, content in old_contents.items():
        (output_dir / filename).write_text(content, encoding="utf-8")

    real_replace = rebuild_mod.os.replace

    def _fail_second_chapter_markdown(source: str | Path, target: str | Path) -> None:
        source_path = Path(source)
        target_path = Path(target)
        if (
            source_path.name == "ch-2.md"
            and source_path.parent != output_dir
            and target_path == output_dir / "ch-2.md"
        ):
            raise OSError("replace failed after ch-1")
        real_replace(source, target)

    monkeypatch.setattr(rebuild_mod.os, "replace", _fail_second_chapter_markdown)

    report = rebuild_book(
        book,
        chapters,
        core_view,
        IntegrityGate(),
        target_chapter_ids=("ch-1", "ch-2"),
        output_dir=output_dir,
        apply=True,
    )

    assert report.status == "failed"
    assert report.reason_codes == ("write_exception:OSError",)
    for filename, content in old_contents.items():
        assert (output_dir / filename).read_text(encoding="utf-8") == content


def test_repeated_rebuilds_produce_equal_rendered_hashes() -> None:
    book, chapters, core_view = _fixture(publication_version=23)

    first = rebuild_book(
        book,
        chapters,
        core_view,
        IntegrityGate(),
        apply=False,
    )
    second = rebuild_book(
        book,
        chapters,
        core_view,
        IntegrityGate(),
        apply=False,
    )

    assert first.status == "planned"
    assert second.status == "planned"
    assert first.rendered_hashes == second.rendered_hashes


def test_committed_rebuild_removes_the_staging_directory(tmp_path: Path) -> None:
    """A committed rebuild must not leave an empty ``.rebuild-staging/`` behind.

    ``rebuild_book`` stages every file under ``<output_dir>/.rebuild-staging``
    and moves them into place with ``os.replace``. The per-run temp dir is
    removed in a ``finally``, but the ``.rebuild-staging`` container itself was
    never cleaned up — so every successful build littered the output directory
    with an empty hidden folder.
    """
    book, chapters, core_view = _fixture(publication_version=7)
    output_dir = tmp_path / "book"

    report = rebuild_book(
        book,
        chapters,
        core_view,
        IntegrityGate(),
        output_dir=output_dir,
        apply=True,
    )

    assert report.status == "committed"
    assert not (output_dir / ".rebuild-staging").exists(), (
        "staging container must be cleaned up after a committed rebuild"
    )


def test_failed_rebuild_also_removes_the_staging_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed rebuild cleans up too — a half-finished build must not leave debris."""
    book, chapters, core_view = _fixture(publication_version=7)
    output_dir = tmp_path / "book"
    output_dir.mkdir(parents=True)

    real_write_text = rebuild_mod._write_text

    def _fail_stage_write(path: Path, content: str) -> None:
        if ".rebuild-staging" in str(path.parent):
            raise OSError("disk full during staging")
        real_write_text(path, content)

    monkeypatch.setattr(rebuild_mod, "_write_text", _fail_stage_write)

    report = rebuild_book(
        book,
        chapters,
        core_view,
        IntegrityGate(),
        output_dir=output_dir,
        apply=True,
    )

    assert report.status == "failed"
    assert not (output_dir / ".rebuild-staging").exists()


def test_staging_directory_is_left_alone_when_another_build_is_in_flight(tmp_path: Path) -> None:
    """Cleanup must not delete a staging root another concurrent build still uses.

    ``rmdir`` only succeeds on an empty directory, so a sibling build holding a
    temp dir inside ``.rebuild-staging`` keeps it alive. This test pins that
    behaviour so the cleanup can never be "optimised" into ``rmtree``.
    """
    book, chapters, core_view = _fixture(publication_version=7)
    output_dir = tmp_path / "book"
    staging_root = output_dir / ".rebuild-staging"
    in_flight = staging_root / "other-build-abc"
    in_flight.mkdir(parents=True)
    (in_flight / "ch-x.md").write_text("in flight", encoding="utf-8")

    report = rebuild_book(
        book,
        chapters,
        core_view,
        IntegrityGate(),
        output_dir=output_dir,
        apply=True,
    )

    assert report.status == "committed"
    assert staging_root.exists(), "a concurrent build's staging dir must survive"
    assert (in_flight / "ch-x.md").read_text(encoding="utf-8") == "in flight"
