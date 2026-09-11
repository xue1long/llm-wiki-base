"""Tests for `partition_writing_technique_merged` (Task 4).

Background (Task 4 of
`docs/superpowers/plans/2026-09-10-novel-wiki-fullbook-readability.md`):

- The current 68 writing-technique-related chapters each cover a
  single small topic, which makes the Book feel fragmented when
  read end-to-end. The plan consolidates them into 8 named
  chapters (人物塑造与设定 / 情节与节奏 / 开篇与签约 / 套路与爽点 /
  描写与文笔 / 题材与世界观 / 心态与职业 / 平台与读者) without losing
  any page_id or disturbing other chapter buckets.

- The function MUST preserve the `partition_pages` coverage
  invariant: `sorted(union(values)) == sorted(snapshot.pages)`.
  A regression that drops or duplicates a page_id breaks the
  whole release.
"""
from __future__ import annotations

from collections import namedtuple

import pytest

from src.kc.views.book.wiki.partition import (
    DEFAULT_WRITING_TECHNIQUE_REGROUP,
    partition_writing_technique_merged,
)


# Minimal stand-in for `WikiSnapshot` — only the `pages` attribute
# is read by the function under test.
PageRecord = namedtuple("PageRecord", ["page_id", "title", "page_type", "primary_taxonomy"])


def _snapshot(pages):
    return type("S", (), {"pages": pages})()


# ─── Default rule shape ────────────────────────────────────────────


def test_default_regroup_rules_have_eight_named_chapters():
    assert len(DEFAULT_WRITING_TECHNIQUE_REGROUP) == 8
    expected_keys = {
        "concept-写作技法-人物塑造与设定",
        "concept-写作技法-情节与节奏",
        "concept-写作技法-开篇与签约",
        "concept-写作技法-套路与爽点",
        "concept-写作技法-描写与文笔",
        "concept-写作技法-题材与世界观",
        "concept-写作技法-心态与职业",
        "concept-写作技法-平台与读者",
    }
    assert set(DEFAULT_WRITING_TECHNIQUE_REGROUP.keys()) == expected_keys


# ─── Basic regroup + coverage invariant ────────────────────────────


def test_writing_pages_distributed_to_eight_buckets():
    pages = [
        PageRecord("p1", "主角人设", "concept", "写作技法"),
        PageRecord("p2", "反派设计", "concept", "写作技法"),
        PageRecord("p3", "情节节奏", "concept", "写作技法"),
        PageRecord("p4", "金手指设定", "concept", "写作技法"),
        PageRecord("p5", "环境描写", "concept", "写作技法"),
        PageRecord("p6", "仙侠题材", "concept", "写作技法"),
        PageRecord("p7", "写作心态", "concept", "写作技法"),
        PageRecord("p8", "平台规则", "concept", "写作技法"),
        PageRecord("p9", "读者分析", "concept", "写作技法"),
    ]
    result = partition_writing_technique_merged(_snapshot(pages))

    # Each writing page lands in exactly one new bucket.
    assert "p1" in result["concept-写作技法-人物塑造与设定"]
    assert "p2" in result["concept-写作技法-人物塑造与设定"]
    assert "p3" in result["concept-写作技法-情节与节奏"]
    assert "p4" in result["concept-写作技法-套路与爽点"]
    assert "p5" in result["concept-写作技法-描写与文笔"] or "p5" in result["concept-写作技法-描写与文笔"]
    assert "p6" in result["concept-写作技法-题材与世界观"] or "p6" in result["concept-写作技法-题材与世界观"]
    assert "p7" in result["concept-写作技法-心态与职业"] or "p7" in result["concept-写作技法-心态与职业"]
    assert "p8" in result["concept-写作技法-平台与读者"] or "p8" in result["concept-写作技法-平台与读者"]
    assert "p9" in result["concept-写作技法-平台与读者"] or "p9" in result["concept-写作技法-平台与读者"]


def test_passthrough_pages_buckets_by_taxonomy():
    """Pages not in any writing-technique chapter must still
    survive the regroup, bucketed by their taxonomy."""
    pages = [
        PageRecord("w1", "主角设计", "concept", "写作技法"),  # regrouped
        PageRecord("e1", "主角", "entity", "人设"),  # passthrough
        PageRecord("c1", "古风设计", "concept", "题材体系"),  # passthrough
        PageRecord("c2", "无明确分类", "concept", ""),  # passthrough (no taxonomy)
    ]
    result = partition_writing_technique_merged(_snapshot(pages))

    # Coverage invariant holds.
    all_pages = {p for ids in result.values() for p in ids}
    assert all_pages == {"w1", "e1", "c1", "c2"}

    # Passthrough pages land somewhere outside the 8 new chapters.
    new_keys = set(DEFAULT_WRITING_TECHNIQUE_REGROUP.keys())
    passthrough_pages = {"e1", "c1", "c2"}
    passthrough_locations = {
        cid for cid, ids in result.items() if cid not in new_keys
    }
    assert passthrough_locations  # at least one passthrough bucket
    passthrough_union = {
        p for cid, ids in result.items() if cid not in new_keys
        for p in ids
    }
    assert passthrough_pages <= passthrough_union


def test_coverage_invariant_with_mixed_pages():
    """Mixed snapshot (writing + passthrough) preserves every
    page_id exactly once."""
    pages = [
        PageRecord("p1", "主角", "concept", "写作技法"),
        PageRecord("p2", "反派", "concept", "写作技法"),
        PageRecord("p3", "金手指", "concept", "写作技法"),
        PageRecord("p4", "SYNTH", "synthesis", "写作技法"),
        PageRecord("e1", "ENT", "entity", "ENT"),
        PageRecord("c1", "TPC", "concept", "TPC"),
        PageRecord("f1", "FALL", "concept", ""),
    ]
    result = partition_writing_technique_merged(_snapshot(pages))
    union = sorted(p for ids in result.values() for p in ids)
    assert union == sorted(["p1", "p2", "p3", "p4", "e1", "c1", "f1"])
    # No duplicates across buckets.
    for cid, ids in result.items():
        assert len(ids) == len(set(ids)), f"duplicate in {cid}: {ids}"


# ─── Edge cases ─────────────────────────────────────────────────────


def test_empty_snapshot_returns_empty_dict():
    result = partition_writing_technique_merged(_snapshot([]))
    assert result == {}


def test_no_writing_pages_yields_no_new_chapters():
    """When no page is a writing-technique page, the function
    must NOT emit any of the 8 new chapter buckets — they would
    be empty."""
    pages = [
        PageRecord("p1", "X", "concept", "题材体系"),
        PageRecord("p2", "Y", "entity", "人设"),
        PageRecord("p3", "Z", "synthesis", "心态"),
    ]
    result = partition_writing_technique_merged(_snapshot(pages))
    new_keys = set(DEFAULT_WRITING_TECHNIQUE_REGROUP.keys())
    assert not (new_keys & set(result.keys()))
    # Coverage invariant still holds.
    union = sorted(p for ids in result.values() for p in ids)
    assert union == sorted(["p1", "p2", "p3"])


def test_unmatched_writing_page_goes_to_catchall_bucket():
    """A writing-technique page whose title matches no rule lands
    in the FIRST rule's bucket (catch-all) so no page is lost."""
    pages = [
        PageRecord("p1", "无关键词的标题", "concept", "写作技法"),
    ]
    result = partition_writing_technique_merged(_snapshot(pages))
    first_rule = next(iter(DEFAULT_WRITING_TECHNIQUE_REGROUP))
    assert result[first_rule] == ("p1",)
    union = sorted(p for ids in result.values() for p in ids)
    assert union == ["p1"]


def test_first_match_wins_on_overlapping_keywords():
    """The page title `金手指反派` matches both `人物塑造与设定`
    (反派) and `套路与爽点` (金手指). DEFAULT order places
    `人物塑造与设定` first, so that bucket wins."""
    pages = [
        PageRecord("p1", "金手指反派", "concept", "写作技法"),
    ]
    result = partition_writing_technique_merged(_snapshot(pages))
    assert "p1" in result["concept-写作技法-人物塑造与设定"]
    assert "p1" not in result.get("concept-写作技法-套路与爽点", ())


def test_empty_rules_raises_value_error():
    with pytest.raises(ValueError, match="at least one entry"):
        partition_writing_technique_merged(
            _snapshot([PageRecord("p1", "X", "concept", "写作技法")]),
            regroup_rules={},
        )


def test_custom_rules_replace_defaults():
    """Caller-provided rules override DEFAULT entirely."""
    import re
    pages = [
        PageRecord("p1", "Foo", "concept", "写作技法"),
        PageRecord("p2", "Bar", "concept", "写作技法"),
    ]
    rules = {"only-bucket": re.compile(r"Foo|Bar")}
    result = partition_writing_technique_merged(
        _snapshot(pages), regroup_rules=rules,
    )
    assert "only-bucket" in result
    assert "concept-写作技法-人物塑造与设定" not in result
    assert sorted(result["only-bucket"]) == ["p1", "p2"]


def test_result_buckets_are_tuples_sorted_within():
    """The result dict's values are tuples, not lists, and the
    page_ids inside are sorted (so the regroup output is
    deterministic across runs)."""
    pages = [
        PageRecord("p_late", "X", "concept", "写作技法"),
        PageRecord("p_early", "Y", "concept", "写作技法"),
    ]
    result = partition_writing_technique_merged(_snapshot(pages))
    for ids in result.values():
        assert isinstance(ids, tuple)
        assert list(ids) == sorted(ids)
