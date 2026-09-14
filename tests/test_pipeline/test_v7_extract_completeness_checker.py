"""Tests for V7 extract Stage 3 completeness checks."""

import pytest

from src.pipeline.v7_extract.completeness_checker import check_completeness
from src.pipeline.v7_extract.doc_classifier import DocType
from tests.test_pipeline.test_v7_extract_doc_classifier import (
    COLLECTION,
    INCOMPLETE_DOC,
    LIST_DOC,
    MULTI_SECTION,
    QA_CHAT,
    SINGLE_METHOD,
    TOOL_DOC,
)


@pytest.mark.parametrize(
    "content,doc_type",
    [
        (SINGLE_METHOD, DocType.SINGLE_METHOD),
        (MULTI_SECTION, DocType.MULTI_SECTION),
        (COLLECTION, DocType.COLLECTION),
        (QA_CHAT, DocType.QA_CHAT),
        (LIST_DOC, DocType.LIST),
        (TOOL_DOC, DocType.TOOL),
    ],
)
def test_known_complete_documents_pass(content, doc_type):
    complete, reason = check_completeness(content, doc_type)

    assert complete is True
    assert reason == ""


def test_incomplete_fixture_is_rejected_with_reason():
    complete, reason = check_completeness(INCOMPLETE_DOC, DocType.INCOMPLETE)

    assert complete is False
    assert reason


def test_promised_count_gap_is_rejected():
    content = "# 15 条写作技巧\n\n1. 只提供了一条技巧。"

    complete, reason = check_completeness(content, DocType.LIST)

    assert complete is False
    assert "promised_count" in reason


@pytest.mark.parametrize("content", ["", "# 只有标题", "# 标题\n\n这是一段很短的引言。"])
def test_empty_or_intro_only_content_is_rejected(content):
    complete, reason = check_completeness(content, DocType.SINGLE_METHOD)

    assert complete is False
    assert reason


def test_long_content_passes_length_gate():
    content = "正文段落。" * 200

    complete, reason = check_completeness(content, DocType.SINGLE_METHOD)

    assert complete is True
    assert reason == ""


def test_incomplete_doc_type_is_always_rejected():
    complete, reason = check_completeness("内容足够长。" * 200, DocType.INCOMPLETE)

    assert complete is False
    assert "doc_type" in reason


def test_llm_fallback_can_confirm_an_ambiguous_document():
    class FakeCompletenessLLM:
        def complete(self, **kwargs):
            assert kwargs["prompt_kind"] == "completeness"
            return '{"complete": true, "reason": "model confirmed complete"}'

    complete, reason = check_completeness(
        "# 标题\n\n简短正文。",
        DocType.SINGLE_METHOD,
        llm=FakeCompletenessLLM(),
    )

    assert complete is True
    assert reason == "model confirmed complete"
