from pathlib import Path

from src.kc.views.book.wiki.compiler import compile_book
from src.kc.views.book.wiki.model import ContentBlock, PageRecord, WikiSnapshot


def _fixture(tmp_path: Path):
    page = PageRecord(
        "p1", "Title", "concept", "concepts/p1.md", "tax", "Summary",
        (ContentBlock("p1:0", "p1", "Heading", "Body", 0),),
        (), "abc", 4, None,
    )
    snapshot = WikiSnapshot("snap-1", str(tmp_path / "wiki"), "v2.0", (page,), ())
    outlines = [{
        "schema_version": "outline-v1",
        "snapshot_id": "snap-1",
        "volumes": [{
            "volume_id": "v1",
            "chapters": [{
                "chapter_id": "c1",
                "title": "Chapter",
                "page_ids": ["p1"],
                "overview_refs": ["p1"],
            }],
        }],
    }]
    return snapshot, outlines, {"p1": page}


def test_plan_manifest_lists_only_written_chapter_files(tmp_path: Path) -> None:
    snapshot, outlines, pages = _fixture(tmp_path)

    artifact = compile_book(
        snapshot,
        outlines,
        pages,
        fingerprint={},
        state_dir=tmp_path / ".index",
        plan_only=True,
    )

    assert not (artifact.version_dir / "v1__c1.md").exists()
    assert artifact.manifest["chapter_files"] == {}
    assert artifact.manifest["planned_chapters"] == ["c1"]
