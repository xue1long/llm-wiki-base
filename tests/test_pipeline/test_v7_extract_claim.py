"""Task 14: Stage 5 claim-level evidence model + canonical spans.

FP10 hardening: ``CanonicalSpan`` stores SOURCE-ABSOLUTE byte offsets
(``start_byte`` / ``end_byte``) *and* item-local CHARACTER offsets
(``char_start`` / ``char_end``). Both views must describe the same text —
``test_canonical_span_byte_offset_against_item_relative_consistent`` is the
guard against mixing the two coordinate systems.
"""
from __future__ import annotations

from src.pipeline.v7_extract.canonical_spans import (
    MAX_SPANS_PER_ITEM,
    CanonicalSpan,
    build_canonical_spans,
)
from src.pipeline.v7_extract.claim import (
    Claim,
    ClaimRisk,
    ClaimSupport,
    EvidenceRef,
)
from src.pipeline.v7_extract.segmentation import CanonicalItem, ItemKind

CJK_TEXT = "知识管理需要稳定的证据链，且每条论断都要能回溯到原文。" * 12


def _make_item(text: str, *, prefix_bytes: int = 0, item_id: str = "item-1"):
    """Source bytes with ``prefix_bytes`` bytes in front of ``text``."""
    body = text.encode("utf-8")
    source_bytes = b"x" * prefix_bytes + body
    item = CanonicalItem(
        item_id=item_id,
        kind=ItemKind.ARTICLE,
        start_byte=prefix_bytes,
        end_byte=prefix_bytes + len(body),
        title="标题",
        text=text,
    )
    return source_bytes, item


def test_claim_carries_evidence_refs_with_byte_spans() -> None:
    source_bytes = b"xxxx" + "扩句法通过增加细节让句子更具体。".encode("utf-8")
    ref = EvidenceRef(
        item_id="item-1",
        item_index=0,
        span_index=1,
        start_byte=4,
        end_byte=4 + len("扩句法通过增加细节让句子更具体。".encode("utf-8")),
    )
    claim = Claim(
        claim_id="c1",
        slot_name="definition",
        text="扩句法通过增加细节让句子更具体。",
        evidence_refs=[ref],
        support=ClaimSupport.SUPPORTED,
        confidence=0.8,
        risk=ClaimRisk.LOW,
    )

    assert claim.evidence_refs == [ref]
    assert claim.support is ClaimSupport.SUPPORTED
    assert claim.risk is ClaimRisk.LOW
    assert ref.excerpt_from(source_bytes) == "扩句法通过增加细节让句子更具体。"
    # byte-length is not char-length for CJK evidence
    assert ref.end_byte - ref.start_byte == 3 * len("扩句法通过增加细节让句子更具体。")


def test_canonical_spans_built_from_canonical_item_byte_range() -> None:
    source_bytes, item = _make_item(CJK_TEXT)
    spans = build_canonical_spans(
        [item], span_target_bytes=300, overlap_bytes=60
    )

    assert len(spans) > 1
    for span in spans:
        byte_len = span.end_byte - span.start_byte
        assert 0 < byte_len <= 300
        assert span.item_id == item.item_id
        assert span.item_index == 0
        assert source_bytes[span.start_byte:span.end_byte].decode("utf-8") == (
            item.text[span.char_start:span.char_end]
        )

    assert spans[0].start_byte == item.start_byte
    assert spans[0].char_start == 0
    assert spans[-1].end_byte == item.end_byte
    assert spans[-1].char_end == len(item.text)
    # overlapping windows, never a gap
    for prev, nxt in zip(spans, spans[1:]):
        assert nxt.start_byte <= prev.end_byte


def test_evidence_ref_excerpt_from_source_bytes_is_deterministic() -> None:
    source_bytes, item = _make_item("原文摘录必须来自 source bytes，而不是 LLM。")
    span = build_canonical_spans([item])[0]
    ref = EvidenceRef(
        item_id=span.item_id,
        item_index=span.item_index,
        span_index=0,
        start_byte=span.start_byte,
        end_byte=span.end_byte,
    )

    first = ref.excerpt_from(source_bytes)
    second = ref.excerpt_from(source_bytes)

    assert first == second == item.text == source_bytes[span.start_byte:span.end_byte].decode("utf-8")


def test_canonical_span_byte_offset_against_item_relative_consistent() -> None:
    """FP10: source-absolute byte offsets vs item-local char offsets."""
    source_bytes, item = _make_item(CJK_TEXT, prefix_bytes=100)
    spans = build_canonical_spans([item], span_target_bytes=90, overlap_bytes=30)

    assert len(spans) > 1
    for span in spans:
        assert source_bytes[span.start_byte:span.end_byte].decode("utf-8") == (
            item.text[span.char_start:span.char_end]
        )
        # source-absolute offsets are shifted by the item's own byte base
        assert span.start_byte == item.start_byte + len(
            item.text[: span.char_start].encode("utf-8")
        )
        assert span.end_byte == item.start_byte + len(
            item.text[: span.char_end].encode("utf-8")
        )

    last = spans[-1]
    assert last.start_byte - item.start_byte != last.char_start  # CJK: 3 bytes/char
    # the item-local view agrees with the source-absolute view for the whole item
    assert item.text.encode("utf-8") == source_bytes[item.start_byte:item.end_byte]


def test_claim_is_substantive_rejects_placeholder() -> None:
    placeholder = Claim(
        claim_id="c1", slot_name="definition", text="需结合原文核对"
    )
    blank = Claim(claim_id="c2", slot_name="definition", text="   ")
    real = Claim(
        claim_id="c3", slot_name="definition", text="  扩句法让句子更具体。 "
    )

    assert placeholder.is_substantive() is False
    assert blank.is_substantive() is False
    assert real.is_substantive() is True


def test_build_canonical_spans_respects_max_spans_per_item() -> None:
    source_bytes, item = _make_item("a" * 1000)
    spans = build_canonical_spans([item], span_target_bytes=8, overlap_bytes=2)

    # uncapped, 8-byte windows with a 6-byte step would yield ~166 spans
    assert len(spans) == MAX_SPANS_PER_ITEM
    assert all(0 < s.end_byte - s.start_byte <= 8 for s in spans)
    assert spans == build_canonical_spans(
        [item], span_target_bytes=8, overlap_bytes=2
    )


def test_canonical_spans_are_deterministic_across_calls() -> None:
    source_bytes, item = _make_item(CJK_TEXT, prefix_bytes=100)

    first = build_canonical_spans([item], span_target_bytes=200, overlap_bytes=50)
    second = build_canonical_spans([item], span_target_bytes=200, overlap_bytes=50)

    assert first == second
    assert [s.span_id for s in first] == [s.span_id for s in second]
    assert all(isinstance(s, CanonicalSpan) for s in first)
    assert len({s.span_id for s in first}) == len(first)
