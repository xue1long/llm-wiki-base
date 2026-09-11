"""Regression tests for the single human-reviewed actionable tag."""

from src.wiki.core.paths import WikiPaths
from src.wiki.core.types import PageType, WikiPage
from src.wiki.features.review import (
    HumanReviewRequiredError,
    has_approved_usage_review,
    record_human_review,
)
from src.wiki.features.tag_namespace import is_valid_value
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.storage.page_writer import read_page, write_page
from scripts.migrate_page_usage import migrate_page_usage


def test_actionable_tag_requires_and_records_human_review(tmp_path):
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)

    assert is_valid_value("用途/可执行")
    assert not has_approved_usage_review(paths, "actionable-page")
    try:
        record_human_review(paths, "actionable-page", "", "approved")
    except HumanReviewRequiredError:
        pass
    else:
        raise AssertionError("empty reviewer must be rejected")

    record_human_review(paths, "actionable-page", "alice", "approved", decided_at=123)
    assert has_approved_usage_review(paths, "actionable-page")


def test_writer_rejects_unreviewed_actionable_tag(tmp_path):
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    page = WikiPage(
        id="actionable-page",
        title="Actionable page",
        type=PageType.CONCEPT,
        body="可执行内容",
        tags=["用途/可执行"],
    )

    try:
        write_page(paths, page)
    except HumanReviewRequiredError:
        pass
    else:
        raise AssertionError("unreviewed actionable tag must be rejected")


def test_usage_migration_is_dry_run_by_default_and_keeps_raw_unchanged(tmp_path):
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    page = WikiPage(
        id="reviewed-page",
        title="Reviewed page",
        type=PageType.CONCEPT,
        body="可执行内容",
    )
    write_page(paths, page)
    raw = paths.raw_sources / "raw.txt"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("raw source", encoding="utf-8")
    record_human_review(paths, page.id, "alice", "approved", decided_at=123)

    preview = migrate_page_usage(tmp_path)
    assert preview["planned"] == [page.id]
    assert "用途/可执行" not in page.tags
    assert "raw source" == raw.read_text(encoding="utf-8")

    before_apply = (paths.wiki_concepts / "reviewed-page.md").read_text(encoding="utf-8")
    result = migrate_page_usage(tmp_path, apply=True)
    assert result["applied"] == [page.id]
    migrated = (paths.wiki_concepts / "reviewed-page.md").read_text(encoding="utf-8")
    assert migrated == before_apply.replace(
        "tags: []", "tags:\n- 用途/可执行", 1
    )
    assert "用途/可执行" in read_page(
        paths.wiki_concepts / "reviewed-page.md"
    ).tags
    assert "raw source" == raw.read_text(encoding="utf-8")


def test_legacy_empty_collections_are_read_as_empty_lists():
    page = WikiPage.from_dict({
        "id": "legacy-empty",
        "title": "Legacy empty",
        "type": "concept",
        "sources": None,
        "relations": None,
        "tags": None,
    })
    assert page.sources == []
    assert page.relations == []
    assert page.tags == []
