"""Golden behavior for deterministic artifact readiness assessment."""

from __future__ import annotations

from src.pipeline.extraction_types import SourceRange, artifact_from_text
from src.pipeline.text_preprocessing import (
    ContentKind,
    ReadinessDecision,
    assess_artifact,
    assess_blocks,
)


def _artifact(text: str, *, source_id: str = "raw/sources/sample.md", fmt: str = "md", method: str = "native_text", ranges=None):
    return artifact_from_text(
        text,
        source_id=source_id,
        format=fmt,
        extraction_method=method,
        ranges=ranges,
    )


def test_short_prose_is_warning_but_not_rejected() -> None:
    result = assess_artifact(_artifact("猫会跑。"))

    assert result.content_kind is ContentKind.PROSE
    assert result.decision is ReadinessDecision.READY_WITH_WARNING
    assert result.reason_codes == ("legitimate_short",)
    assert result.evidence_capacity.chars == 4


def test_short_definition_uses_structure_profile() -> None:
    result = assess_artifact(
        _artifact("F=ma", source_id="raw/sources/formula.md")
    )

    assert result.content_kind is ContentKind.TITLE_DEFINITION
    assert result.decision is ReadinessDecision.READY_WITH_WARNING
    assert "legitimate_short" in result.reason_codes


def test_navigation_and_metadata_have_no_evidence_capacity() -> None:
    result = assess_artifact(
        _artifact(
            "登录/注册\n登录/注册\n北京圣东方国信科技有限公司\n05_题材专题",
            source_id="raw/sources/topic.md",
        )
    )

    assert result.decision is ReadinessDecision.SKIP_NO_CONTENT
    assert "metadata_only" in result.reason_codes
    assert "duplicated_navigation" in result.reason_codes
    assert result.evidence_capacity.chars == 0


def test_repeated_real_prose_is_retained_and_warned() -> None:
    result = assess_artifact(_artifact("\n".join(["这是有效正文。"] * 6)))

    assert result.decision is ReadinessDecision.READY_WITH_WARNING
    assert "high_repetition" in result.reason_codes
    assert result.evidence_capacity.chars > 0
    assert result.repetition_ratio == 1.0


def test_degraded_encoding_quarantines_before_analysis() -> None:
    result = assess_artifact(_artifact("�" * 20))

    assert result.decision is ReadinessDecision.QUARANTINE_DEGRADED
    assert "encoding_degraded" in result.reason_codes


def test_structure_profiles_do_not_use_prose_repetition_rule() -> None:
    table = assess_artifact(
        _artifact("a\tb\na\tb", fmt="xlsx", method="xlsx_cells", source_id="raw/sources/a.xlsx")
    )
    code = assess_artifact(
        _artifact("```\nprint(1)\n```", fmt="md", method="native_text", source_id="raw/sources/a.md")
    )

    assert table.content_kind is ContentKind.TABLE
    assert table.decision is ReadinessDecision.READY
    assert "high_repetition" not in table.reason_codes
    assert code.content_kind is ContentKind.CODE
    assert code.decision is ReadinessDecision.READY


def test_unknown_format_is_unsupported_and_missing_range_is_degraded() -> None:
    unsupported = assess_artifact(
        _artifact("bytes", fmt="bin", method="unsupported", source_id="raw/sources/a.bin")
    )
    no_range = assess_artifact(_artifact(
        "valid body with enough evidence",
        ranges=(),
    ))

    assert unsupported.decision is ReadinessDecision.UNSUPPORTED
    assert "unsupported_format" in unsupported.reason_codes
    assert no_range.decision is ReadinessDecision.QUARANTINE_DEGRADED
    assert "missing_provenance" in no_range.reason_codes


def test_multiline_native_block_keeps_all_line_ranges() -> None:
    result = assess_artifact(_artifact(
        "第一行是有效正文内容。\n第二行继续提供可引用信息。"
    ))

    assert result.decision is ReadinessDecision.READY
    assert result.provenance_complete is True
    assert result.reason_codes == ()


def test_multiline_paragraph_blocks_keep_corresponding_line_ranges() -> None:
    result = assess_artifact(_artifact(
        "第一段第一行提供事实。\n第一段第二行继续提供事实。\n\n"
        "第二段第一行提供事实。\n第二段第二行继续提供事实。"
    ))

    assert result.decision is ReadinessDecision.READY
    assert result.provenance_complete is True


def test_mixed_assessment_keeps_valid_block_and_marks_empty_subblock() -> None:
    artifact = _artifact(
        "有效正文内容超过阈值。\n\n登录/注册",
        ranges=(
            SourceRange("line", 0, 10, 0),
            SourceRange("line", 0, 5, 1),
        ),
    )

    blocks = assess_blocks(artifact)
    result = assess_artifact(artifact)

    assert len(blocks) == 2
    assert result.content_kind is ContentKind.MIXED
    assert result.decision in {ReadinessDecision.READY, ReadinessDecision.READY_WITH_WARNING}
    assert "empty_subblock" in result.reason_codes
    assert result.evidence_capacity.blocks == 1
