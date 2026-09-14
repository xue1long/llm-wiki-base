from __future__ import annotations

import json
from pathlib import Path

from src.pipeline.v7_extract.relation_extractor import PageRelation
from src.pipeline.v7_extract.slot_filler import ConceptPage, CONCEPT_SLOTS
from src.pipeline.v7_extract.audit_logger import AuditLogger
from src.pipeline.v7_extract.wiki_writer import WriteReport, WikiWriter


def _page(page_id: str, source: str) -> ConceptPage:
    return ConceptPage(
        page_id,
        f"标题-{page_id}",
        {name: f"{name} 内容" for name in CONCEPT_SLOTS},
        [source],
    )


def test_writer_creates_pages_index_checkpoint_and_audit_report(tmp_path: Path) -> None:
    writer = WikiWriter(tmp_path)
    pages = [_page("concept-a", "raw-a"), _page("concept-b", "raw-a")]
    relations = [PageRelation("concept-b", "concept-a", "refines")]

    report = writer.commit_and_index(pages, relations)
    second = writer.commit_and_index(pages, relations)

    assert isinstance(report, WriteReport)
    assert report.written == ["concept-a", "concept-b"]
    assert second.written == []
    assert set(second.skipped) == {"concept-a", "concept-b"}
    assert (tmp_path / "wiki" / "concepts" / "concept-a.md").exists()
    index = (tmp_path / "wiki" / "index.md").read_text(encoding="utf-8")
    assert index.count("- **concept-a**") == 1
    assert index.count("- **concept-b**") == 1
    checkpoint = json.loads(
        (tmp_path / ".index" / "v7_checkpoint.json").read_text(encoding="utf-8")
    )
    assert checkpoint["completed"] == ["concept-a", "concept-b"]
    audit = json.loads(
        (tmp_path / ".index" / "extract_report.json").read_text(encoding="utf-8")
    )
    assert audit["raw-a"] == ["concept-a", "concept-b"]


def test_writer_retries_three_times_then_reports_failure(tmp_path: Path) -> None:
    attempts: list[str] = []

    def always_fails(page: ConceptPage, path: Path) -> None:
        attempts.append(page.id)
        raise OSError("disk full")

    writer = WikiWriter(tmp_path, page_writer=always_fails)
    report = writer.commit_and_index([_page("broken", "raw-b")])

    assert attempts == ["broken", "broken", "broken"]
    assert report.written == []
    assert report.failed == {"broken": "disk full"}
    assert not (tmp_path / "wiki" / "concepts" / "broken.md").exists()


def test_writer_checkpoint_does_not_hide_a_missing_page(tmp_path: Path) -> None:
    writer = WikiWriter(tmp_path)
    page = _page("recover", "raw-c")
    writer.commit_and_index([page])
    (tmp_path / "wiki" / "concepts" / "recover.md").unlink()

    report = writer.commit_and_index([page])

    assert report.written == ["recover"]
    assert (tmp_path / "wiki" / "concepts" / "recover.md").exists()


def test_audit_logger_merges_source_mappings_idempotently(tmp_path: Path) -> None:
    logger = AuditLogger(tmp_path / "extract_report.json")

    logger.record("raw-a", ["concept-a"])
    logger.record("raw-a", ["concept-a", "concept-b"])

    assert logger.read() == {"raw-a": ["concept-a", "concept-b"]}
