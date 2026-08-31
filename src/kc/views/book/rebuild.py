"""Book rebuild API with dry-run reporting and staging-first writes."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from src.kc.integrity.orchestrator import IntegrityGate

from .compiler import ChapterRender, CompileError, CompiledBlock, compile_chapter
from .contract import Book, Chapter, KnowledgeBlock
from .core_view import KnowledgeCoreView
from .id_policy import generate_stable_knowledge_block_id
from .markdown import render_chapter
from .template import BookTemplate, BookView


@dataclass(frozen=True)
class BookRebuildReport:
    status: Literal["planned", "committed", "failed"]
    book_id: str
    publication_version: int
    rebuilt_chapter_ids: tuple[str, ...]
    failed_chapter_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    rendered_hashes: dict[str, str]
    not_evaluable: bool = False


class _PublicationVersionSnapshot:
    def __init__(self, core_view: KnowledgeCoreView, publication_version: int) -> None:
        self._core_view = core_view
        self._publication_version = publication_version

    def current_publication_version(self) -> int:
        return self._publication_version

    def __getattr__(self, name: str) -> object:
        return getattr(self._core_view, name)


def _ordered_unique(items: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return tuple(ordered)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _normalize_render(render: ChapterRender) -> ChapterRender:
    normalized_blocks: list[CompiledBlock] = []
    for block in render.blocks:
        knowledge_unit_ids = list(block.knowledge_block.knowledge_unit_ids)
        stable_id = generate_stable_knowledge_block_id(
            render.chapter.id,
            knowledge_unit_ids[0] if knowledge_unit_ids else "empty",
        )
        normalized_blocks.append(
            CompiledBlock(
                knowledge_block=KnowledgeBlock(
                    id=stable_id,
                    chapter_id=block.knowledge_block.chapter_id,
                    block_type=block.knowledge_block.block_type,
                    knowledge_unit_ids=knowledge_unit_ids,
                    statement_refs=list(block.knowledge_block.statement_refs),
                    evidence_refs=list(block.knowledge_block.evidence_refs),
                    knowledge_mode=block.knowledge_block.knowledge_mode,
                ),
                evidence_refs=block.evidence_refs,
                unsupported_fact=block.unsupported_fact,
                reason_codes=block.reason_codes,
            )
        )
    return ChapterRender(
        chapter=render.chapter,
        blocks=tuple(normalized_blocks),
        publication_version=render.publication_version,
        rendered_at=render.rendered_at,
        integrity_report=render.integrity_report,
        reason_codes=render.reason_codes,
        unsupported_fact_count=render.unsupported_fact_count,
        conflicts=render.conflicts,
    )


def _metadata_json(view: BookView, chapter: Chapter, publication_version: int) -> str:
    payload = {
        "book_id": chapter.book_id,
        "chapter_id": chapter.id,
        "stable_key": chapter.stable_key,
        "knowledge_unit_ids": list(view.knowledge_unit_ids),
        "publication_version": publication_version,
        "rendered_hash": view.rendered_hash,
        "sections": list(view.sections),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _selected_chapters(
    book: Book,
    chapters: tuple[Chapter, ...],
    target_chapter_ids: tuple[str, ...] | None,
) -> tuple[tuple[Chapter, ...], tuple[str, ...], str | None]:
    chapter_map = {chapter.id: chapter for chapter in chapters}
    requested_ids = (
        _ordered_unique(target_chapter_ids)
        if target_chapter_ids is not None
        else _ordered_unique(tuple(book.chapter_ids))
    )
    not_in_book = tuple(
        chapter_id for chapter_id in requested_ids if chapter_id not in book.chapter_ids
    )
    if not_in_book:
        return (), not_in_book, "chapter_resolution:not_in_book"
    missing = tuple(chapter_id for chapter_id in requested_ids if chapter_id not in chapter_map)
    if missing:
        return (), missing, "chapter_resolution:missing_chapters"
    return tuple(chapter_map[chapter_id] for chapter_id in requested_ids), (), None


def _stage_paths(stage_dir: Path, chapter_id: str) -> tuple[Path, Path]:
    return stage_dir / f"{chapter_id}.md", stage_dir / f"{chapter_id}.json"


def _commit_stage(stage_dir: Path, output_dir: Path, chapter_ids: tuple[str, ...]) -> None:
    backups: dict[Path, Path | None] = {}
    try:
        for chapter_id in chapter_ids:
            staged_md, staged_json = _stage_paths(stage_dir, chapter_id)
            for staged_path in (staged_md, staged_json):
                target_path = output_dir / staged_path.name
                backup_path = None
                if target_path.exists():
                    backup_path = stage_dir / f"{target_path.name}.bak"
                    os.replace(target_path, backup_path)
                backups[target_path] = backup_path
                os.replace(staged_path, target_path)
    except Exception:
        for target_path, backup_path in backups.items():
            if backup_path is not None and backup_path.exists():
                os.replace(backup_path, target_path)
                continue
            if target_path.exists():
                target_path.unlink()
        raise
    for backup_path in backups.values():
        if backup_path is not None and backup_path.exists():
            backup_path.unlink()


def rebuild_book(
    book: Book,
    chapters: tuple[Chapter, ...],
    core_view: KnowledgeCoreView,
    integrity_gate: IntegrityGate,
    *,
    template: BookTemplate | None = None,
    target_chapter_ids: tuple[str, ...] | None = None,
    output_dir: Path | None = None,
    apply: bool = False,
) -> BookRebuildReport:
    publication_version = core_view.current_publication_version()
    selected, missing, selection_reason = _selected_chapters(book, chapters, target_chapter_ids)
    if missing:
        return BookRebuildReport(
            status="failed",
            book_id=book.id,
            publication_version=publication_version,
            rebuilt_chapter_ids=(),
            failed_chapter_ids=missing,
            reason_codes=(selection_reason or "chapter_resolution:missing_chapters",),
            rendered_hashes={},
        )
    if not selected:
        return BookRebuildReport(
            status="planned",
            book_id=book.id,
            publication_version=publication_version,
            rebuilt_chapter_ids=(),
            failed_chapter_ids=(),
            reason_codes=(),
            rendered_hashes={},
            not_evaluable=True,
        )

    rendered_views: dict[str, BookView] = {}
    rendered_hashes: dict[str, str] = {}
    snapshot_core_view = _PublicationVersionSnapshot(core_view, publication_version)
    for chapter in selected:
        compiled = compile_chapter(chapter, snapshot_core_view, integrity_gate)
        if isinstance(compiled, CompileError):
            return BookRebuildReport(
                status="failed",
                book_id=book.id,
                publication_version=publication_version,
                rebuilt_chapter_ids=tuple(rendered_views),
                failed_chapter_ids=(chapter.id,),
                reason_codes=tuple(compiled.reason_codes),
                rendered_hashes=dict(rendered_hashes),
            )
        try:
            view = render_chapter(_normalize_render(compiled), template=template)
        except Exception as exc:
            return BookRebuildReport(
                status="failed",
                book_id=book.id,
                publication_version=publication_version,
                rebuilt_chapter_ids=tuple(rendered_views),
                failed_chapter_ids=(chapter.id,),
                reason_codes=(f"render_exception:{type(exc).__name__}",),
                rendered_hashes=dict(rendered_hashes),
            )
        rendered_views[chapter.id] = view
        rendered_hashes[chapter.id] = view.rendered_hash

    if not apply:
        return BookRebuildReport(
            status="planned",
            book_id=book.id,
            publication_version=publication_version,
            rebuilt_chapter_ids=tuple(rendered_views),
            failed_chapter_ids=(),
            reason_codes=(),
            rendered_hashes=dict(rendered_hashes),
        )

    if output_dir is None:
        return BookRebuildReport(
            status="failed",
            book_id=book.id,
            publication_version=publication_version,
            rebuilt_chapter_ids=tuple(rendered_views),
            failed_chapter_ids=tuple(rendered_views),
            reason_codes=("write_exception:missing_output_dir",),
            rendered_hashes=dict(rendered_hashes),
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    staging_root = output_dir / ".rebuild-staging"
    staging_root.mkdir(parents=True, exist_ok=True)
    stage_dir = Path(tempfile.mkdtemp(prefix=f"{book.id}-", dir=str(staging_root)))
    try:
        for chapter in selected:
            view = rendered_views[chapter.id]
            staged_md, staged_json = _stage_paths(stage_dir, chapter.id)
            try:
                _write_text(staged_md, view.markdown)
                _write_text(staged_json, _metadata_json(view, chapter, publication_version))
            except Exception as exc:
                return BookRebuildReport(
                    status="failed",
                    book_id=book.id,
                    publication_version=publication_version,
                    rebuilt_chapter_ids=tuple(rendered_views),
                    failed_chapter_ids=(chapter.id,),
                    reason_codes=(f"write_exception:{type(exc).__name__}",),
                    rendered_hashes=dict(rendered_hashes),
                )
        try:
            _commit_stage(stage_dir, output_dir, tuple(rendered_views))
        except Exception as exc:
            return BookRebuildReport(
                status="failed",
                book_id=book.id,
                publication_version=publication_version,
                rebuilt_chapter_ids=tuple(rendered_views),
                failed_chapter_ids=tuple(rendered_views),
                reason_codes=(f"write_exception:{type(exc).__name__}",),
                rendered_hashes=dict(rendered_hashes),
            )
    finally:
        shutil.rmtree(stage_dir, ignore_errors=True)

    return BookRebuildReport(
        status="committed",
        book_id=book.id,
        publication_version=publication_version,
        rebuilt_chapter_ids=tuple(rendered_views),
        failed_chapter_ids=(),
        reason_codes=(),
        rendered_hashes=dict(rendered_hashes),
    )


__all__ = ["BookRebuildReport", "rebuild_book"]
