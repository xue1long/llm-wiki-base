from __future__ import annotations

from pathlib import Path

from src.pipeline.v7_extract.content_filter import ContentFilter, FilterStatus
from src.pipeline.v7_extract.slot_filler import ConceptPage, CONCEPT_SLOTS
from src.pipeline.v7_extract.wiki_writer import WikiWriter
from src.wiki.storage.reviews_queue import ReviewQueue


def test_filter_detects_political_porn_and_plagiarism_categories() -> None:
    result = ContentFilter().scan("政治敏感内容；色情敏感内容；这段内容属于抄袭洗稿。")

    assert result.status is FilterStatus.NEEDS_REVIEW
    assert {match.category for match in result.matches} == {
        "political",
        "pornographic",
        "plagiarism",
    }


def test_filter_clean_content_has_no_false_review_flag() -> None:
    result = ContentFilter().scan("这是关于小说结构、人物动机和节奏安排的普通写作资料。")

    assert result.status is FilterStatus.CLEAN
    assert result.matches == []


def test_filter_enqueue_is_idempotent_and_resolvable(tmp_path: Path) -> None:
    queue = ReviewQueue(tmp_path / "reviews.json")
    content = "正文包含抄袭风险标记。"
    content_filter = ContentFilter(queue=queue)

    first = content_filter.check(
        content,
        source_id="raw-1",
        title="待审素材",
    )
    second = content_filter.check(
        content,
        source_id="raw-1",
        title="待审素材",
    )

    assert first.status is FilterStatus.NEEDS_REVIEW
    assert second.review_id == first.review_id
    items = queue.list()
    assert len(items) == 1
    assert items[0]["status"] == "open"
    queue.resolve(first.review_id, "accepted")
    assert queue.list(status="open") == []
    assert queue.list(status="accepted")[0]["source_id"] == "raw-1"


def test_queue_rejects_invalid_transition(tmp_path: Path) -> None:
    queue = ReviewQueue(tmp_path / "reviews.json")
    review_id = queue.enqueue("raw-2", "素材", [{"category": "political", "term": "政治敏感"}])

    queue.resolve(review_id, "rejected")
    try:
        queue.resolve(review_id, "accepted")
    except ValueError as exc:
        assert "already resolved" in str(exc)
    else:
        raise AssertionError("resolved review must not be resolved twice")


def test_writer_blocks_flagged_page_until_review_is_accepted(tmp_path: Path) -> None:
    queue = ReviewQueue(tmp_path / "reviews.json")
    content_filter = ContentFilter(queue=queue)
    writer = WikiWriter(tmp_path, content_filter=content_filter)
    page = ConceptPage(
        "sensitive",
        "待审概念",
        {name: "这里包含抄袭风险标记" for name in CONCEPT_SLOTS},
        ["raw-sensitive"],
    )

    blocked = writer.commit_and_index([page])

    assert blocked.written == []
    assert blocked.blocked == ["sensitive"]
    review_id = queue.list()[0]["id"]
    assert not (tmp_path / "wiki" / "concepts" / "sensitive.md").exists()

    queue.resolve(review_id, "accepted")
    accepted = writer.commit_and_index([page])

    assert accepted.written == ["sensitive"]
