"""Task 1 contract tests — canonical_raw_key + Target Resolver."""
import pytest

from src.utils.path import canonical_raw_key
from src.wiki.features.target_resolver import (
    ResolutionContext,
    resolve_wiki_target,
)
from src.utils.path import safe_resolve


# ---------------------------------------------------------------------------
# canonical_raw_key —— 单一来源身份（golden vectors）
# ---------------------------------------------------------------------------

def test_canonical_raw_key_relative_and_absolute_agree(tmp_path):
    root = tmp_path
    rel = "raw/sources/01_新手入门/入门教程爽文.md"
    abs_path = str(safe_resolve(root / rel))
    assert canonical_raw_key(abs_path, root) == rel
    assert canonical_raw_key(rel, root) == rel
    assert canonical_raw_key(str(root) + "\\raw\\sources\\01_新手入门\\入门教程爽文.md",
                             root) == rel


def test_canonical_raw_key_nfc_normalizes_nfd():
    import unicodedata
    nfd = unicodedata.normalize("NFD", "raw/sources/教程.md")
    key = canonical_raw_key(nfd, "C:/proj")
    assert key == "raw/sources/教程.md"


def test_canonical_raw_key_collapses_dot_segments(tmp_path):
    root = tmp_path
    key = canonical_raw_key("raw/sources/./a/../a.md", root)
    assert key == "raw/sources/a.md"


def test_canonical_raw_key_refuses_escape(tmp_path):
    root = tmp_path
    with pytest.raises(ValueError):
        canonical_raw_key("../outside.md", root)
    # raw/sources/../../ 只回到 root 内（raw 两级），须三级才越出
    with pytest.raises(ValueError):
        canonical_raw_key("raw/sources/../../../outside.md", root)


def test_canonical_raw_key_absolute_outside_root(tmp_path):
    other = tmp_path / ".." / "other-project" / "a.md"
    with pytest.raises(ValueError):
        canonical_raw_key(str(other), tmp_path)


# ---------------------------------------------------------------------------
# Target Resolver —— 固定优先级 + 安全门
# ---------------------------------------------------------------------------

def _ctx(**kw) -> ResolutionContext:
    base = dict(
        source_candidates=(("raw/sources/入门教程角色篇完善小说角色的技法.md",
                            "入门教程角色篇完善小说角色的技法-abcdef12",
                            "入门教程角色篇完善小说角色的技法"),),
        existing_index=frozenset({"概念甲", "概念乙"}),
        title_index={"概念甲": ("概念甲",), "重名": ("概念甲", "概念乙")},
        aliases={"旧别名": "概念甲"},
    )
    base.update(kw)
    return ResolutionContext(**base)


def test_exact_id_unchanged():
    r = resolve_wiki_target("概念甲", context=_ctx())
    assert r.kind == "exact"
    assert r.canonical_target == "概念甲"
    assert not r.changed


def test_wikilink_alias_and_fragment_stripped():
    r = resolve_wiki_target("[[概念乙|显示]]", context=_ctx())
    assert r.kind == "exact"
    assert r.canonical_target == "概念乙"


def test_source_exact():
    r = resolve_wiki_target("入门教程角色篇完善小说角色的技法-abcdef12", context=_ctx())
    assert r.kind == "source"
    assert r.canonical_target == "入门教程角色篇完善小说角色的技法-abcdef12"


def test_legacy_hash_single_source_match():
    """batch 9 根因：旧 hash + 标题丢词 → 唯一匹配当前 raw stem。"""
    r = resolve_wiki_target("入门教程角色篇完善小说的技法-e8ca1866", context=_ctx())
    assert r.kind == "legacy_hash"
    assert r.canonical_target == "入门教程角色篇完善小说角色的技法-abcdef12"
    assert r.changed


def test_legacy_hash_no_match_stays_unresolved():
    r = resolve_wiki_target("完全不相关概念-12345678", context=_ctx())
    assert r.kind == "unresolved"
    assert r.canonical_target is None


def test_legacy_hash_ambiguous_when_two_sources():
    """同 stem 不同目录的两个 raw → legacy_hash 歧义阻断。"""
    ctx = _ctx(source_candidates=(
        ("raw/sources/a/入门教程角色篇完善小说角色的技法.md",
         "入门教程角色篇完善小说角色的技法-abcdef12",
         "入门教程角色篇完善小说角色的技法"),
        ("raw/sources/b/入门教程角色篇完善小说角色的技法.md",
         "入门教程角色篇完善小说角色的技法-34567890",
         "入门教程角色篇完善小说角色的技法"),
    ))
    r = resolve_wiki_target("入门教程角色篇完善小说的技法-e8ca1866", context=ctx)
    assert r.kind == "ambiguous"
    assert r.canonical_target is None


def test_alias_resolves_when_canonical_exists():
    r = resolve_wiki_target("旧别名", context=_ctx())
    assert r.kind == "alias"
    assert r.canonical_target == "概念甲"


def test_alias_ignored_when_canonical_missing():
    ctx = _ctx(aliases={"坏别名": "不存在页"})
    r = resolve_wiki_target("坏别名", context=ctx)
    assert r.kind == "unresolved"


def test_title_unique_candidate():
    r = resolve_wiki_target("概念甲", context=_ctx(title_index={"概念甲": ("概念甲",)}))
    assert r.kind in ("exact", "title")


def test_title_ambiguous_blocks():
    r = resolve_wiki_target("重名", context=_ctx())
    assert r.kind == "ambiguous"
    assert r.canonical_target is None
    assert "ambiguous" in (r.warning or "")


def test_ordinary_concept_not_rewritten_by_fuzzy_match():
    """安全门：普通概念页不被 source 规则模糊改写。"""
    ctx = _ctx(existing_index=frozenset({"入门教程角色篇完善小说角色的技法-abcdef12"}),)
    r = resolve_wiki_target("入门教程角色篇完善小说的技法", context=ctx)  # 无 hash 后缀
    assert r.kind == "unresolved"
    assert r.canonical_target is None


def test_resolver_is_deterministic_and_idempotent():
    ctx = _ctx()
    first = resolve_wiki_target("入门教程角色篇完善小说的技法-e8ca1866", context=ctx)
    second = resolve_wiki_target(first.canonical_target or "", context=ctx)
    assert second.kind == "source"
    assert second.canonical_target == first.canonical_target
