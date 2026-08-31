"""Contract tests for the evidence-preserving text preprocessing module."""

from __future__ import annotations

from hashlib import sha256

import pytest

from src.pipeline.text_preprocessing import chunk_prompt_blocks, preprocess_source


def test_preprocess_separates_input_and_canonical_hashes() -> None:
    source = "\ufeff第一行\r\n第二行  \r\n\r\n重复内容"

    result = preprocess_source(source, source_id="raw/sources/demo.md")

    assert result.canonical_text == "第一行\n第二行\n\n重复内容"
    assert result.report.input_text_sha256 == sha256(source.encode("utf-8")).hexdigest()
    assert result.report.canonical_text_sha256 == sha256(
        result.canonical_text.encode("utf-8")
    ).hexdigest()
    assert result.report.metrics_scope == "full_input_text"


def test_prompt_blocks_keep_canonical_identity_while_removing_exact_chrome() -> None:
    result = preprocess_source(
        "正文一\n登录/注册\n\n正文二",
        source_id="raw/sources/demo.md",
    )

    assert len(result.prompt_blocks) == 2
    assert [block.ordinal for block in result.prompt_blocks] == [0, 1]
    assert all(block.source_id == "raw/sources/demo.md" for block in result.prompt_blocks)
    assert all(block.block_id for block in result.prompt_blocks)
    assert result.prompt_blocks[0].prompt_content == "正文一"
    assert "登录/注册" not in result.prompt_text
    assert result.report.removed_line_count == 1


def test_repeated_content_is_warned_about_but_not_deleted() -> None:
    source = "\n".join(["重复内容"] * 6)

    result = preprocess_source(source, source_id="raw/sources/repeated.md")

    assert result.prompt_text.count("重复内容") == 6
    assert "high_repetition" in result.report.warnings
    assert result.report.removed_line_count == 0


def test_degraded_text_only_skips_llm_when_explicitly_requested() -> None:
    source = "�" * 20

    continue_result = preprocess_source(source, source_id="raw/sources/bad.md")
    skip_result = preprocess_source(
        source,
        source_id="raw/sources/bad.md",
        skip_llm_on_degraded=True,
    )

    assert continue_result.report.should_skip_llm is False
    assert skip_result.report.should_skip_llm is True


def test_missing_source_id_fails_closed() -> None:
    with pytest.raises(ValueError, match="source_id"):
        preprocess_source("正文")


def test_chunk_prompt_blocks_preserves_order_and_rejects_oversized_block() -> None:
    prepared = preprocess_source(
        "一段\n\n二段\n\n三段",
        source_id="raw/sources/chunked.md",
    )

    chunks = chunk_prompt_blocks(prepared.prompt_blocks, max_chars=5)

    assert [[block.block_id for block in chunk] for chunk in chunks] == [
        [prepared.prompt_blocks[0].block_id],
        [prepared.prompt_blocks[1].block_id],
        [prepared.prompt_blocks[2].block_id],
    ]
    with pytest.raises(ValueError, match="oversized prompt block"):
        chunk_prompt_blocks(prepared.prompt_blocks, max_chars=1)
