"""Task 1: unified tag normalization contract."""
from src.wiki.features.tag_namespace import normalize_tags


def test_maps_legacy_prefixes():
    # 兼容政策（策略 1）：任何带标签页面自动补 UGC 双标签（素材/ugc + 可信度/ugc）
    result = normalize_tags(["genre/玄幻", "func/教程"])
    assert result.tags == ["题材/玄幻", "功能/教程", "素材/ugc", "可信度/ugc"]
    assert result.mapped == {
        "genre/玄幻": "题材/玄幻",
        "func/教程": "功能/教程",
    }
    assert result.removed == []
    assert result.mandatory_added == ["素材/ugc", "可信度/ugc"]


def test_keeps_valid_tags():
    # 兼容政策（策略 1）：任何带标签页面自动补 UGC 双标签（素材/ugc + 可信度/ugc）
    result = normalize_tags(["题材/玄幻", "功能/教程"])
    assert result.tags == ["题材/玄幻", "功能/教程", "素材/ugc", "可信度/ugc"]
    assert result.mapped == {}
    assert result.removed == []
    assert result.mandatory_added == ["素材/ugc", "可信度/ugc"]


def test_removes_unknown_prefix_and_invalid_value():
    result = normalize_tags(["genre/穿越", "func/结构", "whatever/tag"])
    assert result.tags == []
    assert set(result.removed) == {"genre/穿越", "func/结构", "whatever/tag"}
    assert result.warnings


def test_tagged_page_adds_current_mandatory_pair():
    result = normalize_tags(["题材/玄幻"], source_kind="concept")
    assert result.tags == ["题材/玄幻", "素材/ugc", "可信度/ugc"]
    assert result.mandatory_added == ["素材/ugc", "可信度/ugc"]


def test_ugc_adds_both_mandatory_tags():
    result = normalize_tags(["功能/教程"], source_kind="ugc")
    assert result.tags == ["功能/教程", "素材/ugc", "可信度/ugc"]
    assert result.mandatory_added == ["素材/ugc", "可信度/ugc"]


def test_normalization_is_idempotent():
    first = normalize_tags(["genre/玄幻", "func/教程"], source_kind="ugc")
    second = normalize_tags(first.tags, source_kind="ugc")
    assert second.tags == first.tags
    assert second.mapped == {}
    assert second.removed == []
