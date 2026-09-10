from datetime import datetime, timezone

from src.wiki.migrate.v2_frontmatter import (
    convert_frontmatter,
    convert_frontmatter_and_body,
)


def test_concept_card_maps_canonical_and_extra_fields():
    value = {
        "title": "测试",
        "version": "v2.1",
        "tags": ["a", "b"],
        "processing_depth": "concept",
        "source_grade": "A",
        "platform": "B站",
        "url": "https://example.test/video",
        "author": "N/A",
        "category": "AI技术",
        "maturity": "A级-可借鉴",
        "taxonomy_sub": "AI编程",
        "created": "2026-06-18",
        "updated": "2026-06-18T12:34:56",
        "use_context": "build",
        "workflow_state": "ready",
        "summary": "测试摘要",
    }

    out = convert_frontmatter(value, file_stem="BVxxx")

    assert out["id"] == "BVxxx"
    assert out["title"] == "测试"
    assert out["type"] == "concept"
    assert out["sources"] == ["https://example.test/video"]
    assert out["created_at"] == 1781740800000
    assert out["updated_at"] == 1781786096000
    assert out["tags"] == ["a", "b"]
    assert out["processing_depth"] == "concept"
    assert out["platform"] == "B站"
    assert out["use_context"] == "build"
    assert out["v2_origin"] is True
    assert out["capture_type"] == "video-transcript"
    assert out["_ko_extra"]["version"] == "v2.1"
    assert out["_ko_extra"]["author"] == "N/A"
    assert out["_ko_extra"]["summary"] == "测试摘要"
    assert out["_ko_extra"]["_v2_tags_original"] == ["a", "b"]


def test_entity_aliases_and_instance_of_are_preserved_in_extra():
    out = convert_frontmatter(
        {
            "title": "Claude Code",
            "type": "entity",
            "aliases": ["claude-code", "ClaudeCode"],
            "instance_of": "工具",
        },
        file_stem="Claude Code",
    )

    assert out["type"] == "entity"
    assert out["_ko_extra"]["aliases"] == ["claude-code", "ClaudeCode"]
    assert out["_ko_extra"]["custom_type"] == "工具"
    assert out["_ko_extra"]["instance_of"] == "工具"


def test_datetime_and_numeric_dates_are_accepted():
    out = convert_frontmatter(
        {
            "created": datetime(2026, 6, 18, tzinfo=timezone.utc),
            "updated": 1781786096000,
        },
        file_stem="x",
    )

    assert out["created_at"] == 1781740800000
    assert out["updated_at"] == 1781786096000


def test_unknown_and_invalid_values_are_fail_soft_and_replayable():
    value = {
        "title": "",
        "created": "not-a-date",
        "unknown_field": {"nested": True},
    }

    out = convert_frontmatter(value, file_stem="broken")

    assert out["id"] == "broken"
    assert out["title"] == "broken"
    assert out["created_at"] == 0
    assert out["_ko_extra"]["_v2_unknown_fields"] == {
        "unknown_field": {"nested": True}
    }
    assert "invalid created" in out["_ko_extra"]["_migration_errors"]
    assert out["_ko_extra"]["_v2_frontmatter_original"] == value


def test_convert_frontmatter_and_body_adds_marker_once_for_concepts():
    fm, body = convert_frontmatter_and_body(
        {"title": "概念", "platform": "B站"},
        file_stem="concept",
        body="## 核心观点\n内容",
    )

    assert fm["type"] == "concept"
    assert fm["capture_type"] == "video-transcript"
    assert fm["v2_origin"] is True
    assert body.startswith("<!-- capture-type: video-transcript -->\n")

    _, unchanged = convert_frontmatter_and_body(
        {"title": "概念", "platform": "B站"},
        file_stem="concept",
        body=body,
    )
    assert unchanged == body


def test_entity_body_is_not_marked_by_default():
    fm, body = convert_frontmatter_and_body(
        {"title": "工具", "type": "entity"},
        file_stem="tool",
        body="## 基本信息\n内容",
    )

    assert fm["type"] == "entity"
    assert body == "## 基本信息\n内容"
