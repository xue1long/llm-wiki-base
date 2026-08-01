"""Tests for src/wiki/tag_namespace.py."""
from src.wiki.features.tag_namespace import TAG_PREFIXES, is_valid, parse, validate_tags


def test_valid():
    """Valid tags use one of 10 Chinese controlled prefixes."""
    assert is_valid("题材/现言")
    assert is_valid("功能/教程")
    assert is_valid("角色/总裁")
    assert is_valid("事件/冲突")
    assert is_valid("情绪/甜宠")
    assert is_valid("实体/起点")
    assert is_valid("场景阶段/开篇")
    assert is_valid("状态/完结")
    assert is_valid("素材/ugc")
    assert is_valid("可信度/book")
    # All 10 prefixes registered
    assert len(TAG_PREFIXES) == 10


def test_invalid():
    """Tags without controlled prefix are invalid."""
    assert not is_valid("foo/bar")
    assert not is_valid("nope")
    assert not is_valid("")
    assert not is_valid("题材-no-slash")
    assert not is_valid("/no-prefix")
    # Legacy English prefixes are no longer valid after the CJK cut-over
    assert not is_valid("genre/玄幻")
    assert not is_valid("func/教程")


def test_parse():
    """parse() returns (prefix, name) for valid tags, None for invalid."""
    assert parse("题材/现言") == ("题材", "现言")
    assert parse("场景阶段/开篇") == ("场景阶段", "开篇")
    assert parse("foo/bar") is None
    assert parse("no-slash") is None


def test_validate_tags_returns_invalid():
    """validate_tags returns list of invalid tags."""
    tags = ["题材/现言", "foo/bar", "实体/起点", "", "情绪"]
    invalid = validate_tags(tags)
    assert invalid == ["foo/bar", "", "情绪"]
