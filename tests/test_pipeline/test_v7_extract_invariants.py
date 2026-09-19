"""InvariantReport 字段扩展 — i5_gap_at_tail + i5_gap_bytes。

新增两个字段供 Stage 3/Stage 7 区分"末尾小 gap（自然 ASR 烂尾）" vs
"中间 gap / 大末尾 gap（真分段 bug）"。I5 严格性本身保留。

Plan: docs/superpowers/plans/2026-09-19-v7-stage2-i5-lineage-unblock.md Task 1
"""
from __future__ import annotations

from src.pipeline.v7_extract.invariants import (
    InvariantReport,
    validate_segmentation_invariants,
)
from src.pipeline.v7_extract.segmentation import CanonicalItem, ItemKind


def _make_item(*, item_id: str, start_byte: int, end_byte: int) -> CanonicalItem:
    return CanonicalItem(
        item_id=item_id,
        kind=ItemKind.ARTICLE,
        start_byte=start_byte,
        end_byte=end_byte,
        title=None,
        text="x" * (end_byte - start_byte),
        boundary_sources=["test"],
        confidence=1.0,
    )


# Round 2 P0 加固（场景 1 人员缺位）：防止接手 dev 漏改 invariants.py
def test_invariant_report_has_i5_gap_at_tail_field():
    """InvariantReport 必须有 i5_gap_at_tail 字段 — Task 1 实施 hard check。"""
    report = InvariantReport(
        i1_nonempty=True, i2_boundaries_valid=True,
        i3_sorted=True, i4_non_overlapping=True,
        i5_complete_accounting=True,
    )
    assert hasattr(report, "i5_gap_at_tail")
    assert hasattr(report, "i5_gap_bytes")


def test_tail_gap_at_end_of_source_detected():
    """末尾 gap（items 末尾留几字节）→ i5_gap_at_tail=True + bytes 正确。"""
    items = [
        _make_item(item_id="a", start_byte=0, end_byte=100),
        _make_item(item_id="b", start_byte=100, end_byte=190),  # 末尾留 10 字节
    ]
    report = validate_segmentation_invariants(items, source_size=200)
    assert report.i5_complete_accounting is False  # I5 真没过
    assert report.i5_gap_at_tail is True  # 但只在末尾
    assert report.i5_gap_bytes == 10  # gap 大小


def test_middle_gap_not_tail_residue():
    """中间 gap（items 留空缺）→ i5_gap_at_tail=False。"""
    items = [
        _make_item(item_id="a", start_byte=0, end_byte=50),
        _make_item(item_id="b", start_byte=100, end_byte=200),  # 中间 50 字节 gap
    ]
    report = validate_segmentation_invariants(items, source_size=200)
    assert report.i5_complete_accounting is False
    assert report.i5_gap_at_tail is False  # 不是末尾 gap


def test_complete_coverage_gap_bytes_zero():
    """完整覆盖（I5 过）→ i5_gap_at_tail=False + i5_gap_bytes=0。"""
    items = [
        _make_item(item_id="a", start_byte=0, end_byte=100),
        _make_item(item_id="b", start_byte=100, end_byte=200),
    ]
    report = validate_segmentation_invariants(items, source_size=200)
    assert report.i5_complete_accounting is True
    assert report.i5_gap_at_tail is False
    assert report.i5_gap_bytes == 0


def test_all_pass_property_unchanged_with_new_fields():
    """all_pass 不被新字段影响（I5 严格性保留）。"""
    items = [
        _make_item(item_id="a", start_byte=0, end_byte=100),
        _make_item(item_id="b", start_byte=100, end_byte=190),
    ]
    report = validate_segmentation_invariants(items, source_size=200)
    # i5 真没过 → all_pass=False（不被新字段污染）
    assert report.all_pass is False
    # 新字段不影响 all_pass 计算
    assert report.i5_gap_at_tail is True  # 但 gap 在末尾