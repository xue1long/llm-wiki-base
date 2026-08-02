"""Tests for src/wiki/tag_namespace.py."""
from src.wiki.features.tag_namespace import (
    TAG_PREFIXES, TAG_VALUES, MANDATORY_PAIRS,
    is_valid, is_valid_value, parse,
    validate_tags, validate_tag_values, missing_mandatory_tags,
    allowed_values_for, build_tag_prompt_section,
)


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


# -----------------------------------------------------------------------
# TAG_VALUES — value domain constraints
# -----------------------------------------------------------------------


def test_tag_values_all_prefixes_have_entries():
    """Every prefix in TAG_PREFIXES has a corresponding TAG_VALUES entry."""
    for prefix in TAG_PREFIXES:
        assert prefix in TAG_VALUES, f"Missing TAG_VALUES entry for {prefix}"


def test_is_valid_value_free_form():
    """Prefixes with None (free-form) accept any value."""
    assert is_valid_value("角色/总裁")
    assert is_valid_value("事件/冲突")
    assert is_valid_value("实体/起点")


def test_is_valid_value_constrained():
    """Prefixes with a set constrain allowed values."""
    assert is_valid_value("题材/现言")
    assert is_valid_value("题材/玄幻")
    assert not is_valid_value("题材/unknown-genre")
    assert is_valid_value("状态/完结")
    assert not is_valid_value("状态/deleted")


def test_allowed_values_for():
    """allowed_values_for returns set or None."""
    assert allowed_values_for("题材") is not None
    assert "现言" in allowed_values_for("题材")
    assert allowed_values_for("角色") is None


def test_validate_tag_values():
    """validate_tag_values catches out-of-domain values."""
    tags = ["题材/现言", "题材/bogus", "角色/any", "状态/完结", "状态/nope", "invalid"]
    invalid = validate_tag_values(tags)
    assert "题材/bogus" in invalid
    assert "状态/nope" in invalid
    assert "invalid" in invalid
    assert "题材/现言" not in invalid
    assert "角色/any" not in invalid
    assert len(invalid) == 3


# -----------------------------------------------------------------------
# MANDATORY_PAIRS
# -----------------------------------------------------------------------


def test_mandatory_pairs_empty_by_default():
    """MANDATORY_PAIRS starts empty."""
    assert MANDATORY_PAIRS == []


def test_missing_mandatory_tags():
    """missing_mandatory_tags reports absent mandatory pairs."""
    # Temporarily set mandatory pairs
    import src.wiki.features.tag_namespace as tn
    original = list(tn.MANDATORY_PAIRS)
    try:
        tn.MANDATORY_PAIRS[:] = [("状态", "完结"), ("功能", "教程")]
        missing = missing_mandatory_tags(["题材/现言", "状态/完结"])
        assert missing == ["功能/教程"]
    finally:
        tn.MANDATORY_PAIRS[:] = original


def test_missing_mandatory_tags_all_present():
    """Returns empty list when all mandatory tags are present."""
    import src.wiki.features.tag_namespace as tn
    original = list(tn.MANDATORY_PAIRS)
    try:
        tn.MANDATORY_PAIRS[:] = [("状态", "完结")]
        missing = missing_mandatory_tags(["状态/完结", "题材/现言"])
        assert missing == []
    finally:
        tn.MANDATORY_PAIRS[:] = original


# -----------------------------------------------------------------------
# LLM prompt builder
# -----------------------------------------------------------------------


def test_build_tag_prompt_section_contains_all_prefixes():
    """build_tag_prompt_section mentions every registered prefix."""
    prompt = build_tag_prompt_section()
    for prefix in TAG_PREFIXES:
        assert prefix in prompt


def test_build_tag_prompt_section_lists_allowed_values():
    """Constrained prefixes list valid values in the prompt."""
    prompt = build_tag_prompt_section()
    assert "现言" in prompt
    assert "古言" in prompt
    assert "完结" in prompt
    assert "连载中" in prompt


def test_build_tag_prompt_section_marks_free_form():
    """Free-form prefixes are marked as such."""
    prompt = build_tag_prompt_section()
    assert "free-form" in prompt


def test_build_tag_prompt_section_includes_mandatory():
    """When mandatory pairs exist, they appear in the prompt."""
    import src.wiki.features.tag_namespace as tn
    original = list(tn.MANDATORY_PAIRS)
    try:
        tn.MANDATORY_PAIRS[:] = [("功能", "教程")]
        prompt = build_tag_prompt_section()
        assert "Mandatory tags" in prompt
        assert "功能/教程" in prompt
    finally:
        tn.MANDATORY_PAIRS[:] = original
