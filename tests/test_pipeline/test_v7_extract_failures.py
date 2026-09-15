"""T1.6: failures.py — D4/D10/D11 + P2 + D7."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.pipeline.v7_extract import failures as f
from src.pipeline.v7_extract.failures import (
    ExtractionResult,
    ExtractionStatus,
    V7_SOURCE_TAG,
    _read_queue,
    _write_queue,
    enqueue_failure,
    filter_failed_topics,
    sanitize_payload,
)


# ---------------------------------------------------------------------------
# ExtractionResult / ExtractionStatus
# ---------------------------------------------------------------------------

def test_extraction_status_values():
    assert ExtractionStatus.OK == "ok"
    assert ExtractionStatus.NEEDS_REVIEW == "needs_review"
    assert ExtractionStatus.INCOMPLETE == "incomplete"


def test_extraction_result_defaults():
    r = ExtractionResult(status=ExtractionStatus.OK, source_id="x.md")
    assert r.pages == []
    assert r.review_reasons == []
    assert r.blocked_topic_ids == []
    assert r.failure_stage is None


def test_extraction_result_full_construction():
    r = ExtractionResult(
        status=ExtractionStatus.NEEDS_REVIEW,
        source_id="x.md",
        pages=["p1", "p2"],
        review_reasons=["stage5_evidence_failed"],
        blocked_topic_ids=["topic-3"],
        failure_stage="stage5",
    )
    assert r.status == ExtractionStatus.NEEDS_REVIEW
    assert r.pages == ["p1", "p2"]
    assert r.review_reasons == ["stage5_evidence_failed"]
    assert r.blocked_topic_ids == ["topic-3"]
    assert r.failure_stage == "stage5"


# ---------------------------------------------------------------------------
# D11: sanitize_payload
# ---------------------------------------------------------------------------

def test_sanitize_redacts_sensitive_keys():
    payload = {"api_key": "sk-secret", "email": "x@y.com", "ok": "fine"}
    out = sanitize_payload(payload)
    assert out["api_key"] == "[REDACTED]"
    assert out["email"] == "[REDACTED]"
    assert out["ok"] == "fine"


def test_sanitize_is_case_insensitive_on_keys():
    payload = {"API_KEY": "secret", "Email": "x@y"}
    out = sanitize_payload(payload)
    assert out["API_KEY"] == "[REDACTED]"
    assert out["Email"] == "[REDACTED]"


def test_sanitize_truncates_long_strings():
    long = "x" * 1000
    out = sanitize_payload({"body": long})
    assert len(out["body"]) == 500 + len("...")
    assert out["body"].endswith("...")


def test_sanitize_does_not_truncate_short_strings():
    out = sanitize_payload({"body": "short"})
    assert out["body"] == "short"


def test_sanitize_recurses_into_nested():
    payload = {
        "outer": {
            "inner": {"api_key": "x", "ok": "y"},
            "list": [{"password": "z"}, {"email": "x@y"}],
        }
    }
    out = sanitize_payload(payload)
    assert out["outer"]["inner"]["api_key"] == "[REDACTED]"
    assert out["outer"]["inner"]["ok"] == "y"
    assert out["outer"]["list"][0]["password"] == "[REDACTED]"
    assert out["outer"]["list"][1]["email"] == "[REDACTED]"


def test_sanitize_passes_through_non_dict_non_string():
    assert sanitize_payload(42) == 42
    assert sanitize_payload(3.14) == 3.14
    assert sanitize_payload(None) is None
    assert sanitize_payload(True) is True


def test_sanitize_passes_through_list_of_non_dict():
    assert sanitize_payload([1, 2, 3]) == [1, 2, 3]


def test_sanitize_keeps_short_string_in_list():
    out = sanitize_payload(["short"])
    assert out == ["short"]


# ---------------------------------------------------------------------------
# D10 + D4: enqueue_failure writes v7-tagged item to shared queue
# ---------------------------------------------------------------------------

def test_enqueue_writes_v7_tagged_item(tmp_path):
    path = tmp_path / "reviews_queue.json"
    review_id = enqueue_failure(
        source_id="raw/x.md",
        stage="stage1",
        reason="LLM timeout",
        payload={"raw_response": "..."},
        queue_path=path,
    )
    assert review_id.startswith("v7fail-")           # T3 stable prefix

    items = _read_queue(path)
    assert len(items) == 1
    item = items[0]
    assert item["id"] == review_id
    assert item["source"] == V7_SOURCE_TAG            # D10
    assert item["source"] == "v7_extract"
    assert item["failure_stage"] == "stage1"
    assert item["reason"] == "LLM timeout"
    assert item["source_id"] == "raw/x.md"
    assert item["status"] == "open"
    assert "created_at" in item
    assert "last_seen_at" in item
    assert item["attempts"] == 1


def test_enqueue_sanitizes_payload(tmp_path):
    path = tmp_path / "reviews_queue.json"
    enqueue_failure(
        source_id="x",
        stage="stage1",
        reason="r",
        payload={"api_key": "sk-xxx", "ok": "fine"},
        queue_path=path,
    )
    items = _read_queue(path)
    assert items[0]["payload"]["api_key"] == "[REDACTED]"  # D11
    assert items[0]["payload"]["ok"] == "fine"


def test_enqueue_multiple_items_accumulate(tmp_path):
    path = tmp_path / "reviews_queue.json"
    enqueue_failure("a", "stage1", reason="r1", queue_path=path)
    enqueue_failure("b", "stage5", reason="r2", queue_path=path)
    enqueue_failure("c", "stage3", reason="r3", queue_path=path)
    items = _read_queue(path)
    assert len(items) == 3
    assert [it["source_id"] for it in items] == ["a", "b", "c"]
    assert [it["failure_stage"] for it in items] == ["stage1", "stage5", "stage3"]


def test_enqueue_coexists_with_generator_items(tmp_path):
    """D4: the queue file is shared with the Generator pipeline; we
    must not clobber its items."""
    path = tmp_path / "reviews_queue.json"
    # Simulate an existing Generator item
    _write_queue(path, [{
        "id": "content-abc123",
        "source_id": "gen/x.md",
        "title": "existing item",
        "matches": [],
        "content_hash": "",
        "status": "open",
    }])

    enqueue_failure(
        source_id="v7/y.md",
        stage="stage5",
        reason="r",
        queue_path=path,
    )

    items = _read_queue(path)
    assert len(items) == 2
    # Generator item preserved
    assert items[0]["id"] == "content-abc123"
    assert items[0].get("source") != "v7_extract"
    # v7 item tagged
    assert items[1]["source"] == "v7_extract"
    assert items[1]["source_id"] == "v7/y.md"


def test_read_handles_missing_file(tmp_path):
    assert _read_queue(tmp_path / "nope.json") == []


def test_read_handles_corrupt_json(tmp_path):
    p = tmp_path / "corrupt.json"
    p.write_text("{not valid json", encoding="utf-8")
    assert _read_queue(p) == []


# ---------------------------------------------------------------------------
# T3 queue core: 新签名 + P12 加固 + R15/D11 兼容性
# ---------------------------------------------------------------------------

def test_enqueue_failure_new_signature_accepts_all_kwargs(tmp_path):
    """T3: 新签名所有 keyword 参数(page_id / topic_id / content_hash /
    prompt_kind / provider)都应生效,且 reason 必须 keyword-only。"""
    path = tmp_path / "reviews_queue.json"
    review_id = enqueue_failure(
        source_id="raw/source_a.md",
        stage="stage5",
        page_id="48d50307-writing-techniques",
        topic_id="writing-techniques",
        reason="evidence_failed",
        content_hash="abc123",
        prompt_kind="fill_slots",
        provider="ollama:qwen2.5:7b",
        payload={"raw": "context"},
        queue_path=path,
    )
    assert review_id.startswith("v7fail-")

    items = _read_queue(path)
    assert len(items) == 1
    item = items[0]
    assert item["page_id"] == "48d50307-writing-techniques"
    assert item["topic_id"] == "writing-techniques"
    assert item["content_hash"] == "abc123"
    assert item["last_prompt_kind"] == "fill_slots"
    assert item["last_provider"] == "ollama:qwen2.5:7b"
    assert item["attempts"] == 1


def test_enqueue_failure_reason_keyword_only(tmp_path):
    """T3: ``reason`` 是 keyword-only 必填,位置形式调用应报错。"""
    path = tmp_path / "reviews_queue.json"
    with pytest.raises(TypeError):
        # 位置形式传 reason 不再被允许
        enqueue_failure("a", "stage1", "r1", queue_path=path)


def test_enqueue_failure_p12_appends_prompt_and_provider_tags(tmp_path):
    """P12 加固: provider + prompt_kind 非空时进入 queue item 的 reason
    字段,便于 triage。"""
    path = tmp_path / "reviews_queue.json"
    enqueue_failure(
        source_id="raw/source_a.md",
        stage="stage5",
        reason="stage5_llm_error",
        prompt_kind="fill_slots",
        provider="ollama:qwen2.5:7b",
        queue_path=path,
    )
    items = _read_queue(path)
    reason = items[0]["reason"]
    assert "stage5_llm_error" in reason
    assert "prompt=fill_slots" in reason
    assert "provider=ollama:qwen2.5:7b" in reason


def test_enqueue_failure_p12_no_tags_when_prompt_provider_empty(tmp_path):
    """P12: 当 prompt_kind / provider 都为空时,reason 不应追加标签。"""
    path = tmp_path / "reviews_queue.json"
    enqueue_failure(
        source_id="raw/source_a.md",
        stage="stage1",
        reason="pure_reason",
        queue_path=path,
    )
    items = _read_queue(path)
    assert items[0]["reason"] == "pure_reason"
    assert "prompt=" not in items[0]["reason"]
    assert "provider=" not in items[0]["reason"]


def test_enqueue_failure_payload_sanitize_still_applies(tmp_path):
    """R15 / D11: 新签名下,payload 中的 api_key / email / phone 仍被
    sanitize 为 ``[REDACTED]``。"""
    path = tmp_path / "reviews_queue.json"
    enqueue_failure(
        source_id="raw/source_a.md",
        stage="stage5",
        reason="evidence_failed",
        page_id="48d50307-writing-techniques",
        payload={
            "api_key": "sk-secret",
            "email": "x@y.com",
            "phone": "555-1234",
            "ok": "fine",
        },
        queue_path=path,
    )
    items = _read_queue(path)
    payload = items[0]["payload"]
    assert payload["api_key"] == "[REDACTED]"
    assert payload["email"] == "[REDACTED]"
    assert payload["phone"] == "[REDACTED]"
    assert payload["ok"] == "fine"


# ---------------------------------------------------------------------------
# D7: filter_failed_topics
# ---------------------------------------------------------------------------

def test_filter_drops_only_failed_topic_ids():
    class P:
        def __init__(self, tid):
            self.topic_id = tid

    pages = [P("a"), P("b"), P("c"), P("d")]
    out = filter_failed_topics(pages, ["b", "d"])
    assert [p.topic_id for p in out] == ["a", "c"]


def test_filter_with_no_failures_returns_all():
    class P:
        def __init__(self, tid):
            self.topic_id = tid

    pages = [P("a"), P("b")]
    assert filter_failed_topics(pages, []) == pages


def test_filter_preserves_pages_without_topic_id_attribute():
    """D7: if a page lacks topic_id (legacy data), keep it — don't drop."""
    class P:
        pass

    p = P()
    p.some_attr = "x"
    out = filter_failed_topics([p], ["some_other_topic"])
    assert out == [p]


def test_filter_with_empty_pages_returns_empty():
    assert filter_failed_topics([], ["x"]) == []


# ---------------------------------------------------------------------------
# V7_SOURCE_TAG constant
# ---------------------------------------------------------------------------

def test_v7_source_tag_value():
    assert V7_SOURCE_TAG == "v7_extract"


# ---------------------------------------------------------------------------
# Wave 2 / Task 2: ExtractionStatus five-state + ExtractionResult five-state
# + legacy_status mapping (plan §2.2.1).
# ---------------------------------------------------------------------------

import hashlib  # noqa: E402


def test_extraction_status_seven_values():
    """plan §2.2.1: v3 three values + four new Wave 2 values = 7 total."""
    values = {member.value for member in ExtractionStatus}
    assert values == {
        # v3 legacy (kept for backward compat).
        "ok",
        "needs_review",
        "incomplete",
        # Wave 2 new.
        "written",
        "blocked",
        "failed",
        "skipped",
    }


def test_extraction_result_to_dict_full_keys():
    """to_dict() exposes both five-state status and v3 legacy_status."""
    r = ExtractionResult(
        status=ExtractionStatus.WRITTEN,
        source_id="raw/a.md",
        source_md5=hashlib.md5(b"hello").hexdigest(),
        pages=["p1", "p2"],
        written_page_ids=["p1"],
        blocked_page_ids=[],
        failed_page_ids=[],
        review_reasons=["stale_review"],
        blocked_topic_ids=["topic-x"],
        failure_stage="stage5",
        attempts=2,
    )
    d = r.to_dict()
    assert d["status"] == "written"
    assert d["legacy_status"] == "ok"          # WRITTEN → legacy OK
    assert d["source_id"] == "raw/a.md"
    assert d["source_md5"] == hashlib.md5(b"hello").hexdigest()
    assert d["written_page_ids"] == ["p1"]
    assert d["blocked_page_ids"] == []
    assert d["failed_page_ids"] == []
    assert d["review_reasons"] == ["stale_review"]
    assert d["blocked_topic_ids"] == ["topic-x"]
    assert d["failure_stage"] == "stage5"
    assert d["attempts"] == 2


def test_extraction_result_legacy_mapping_written():
    r = ExtractionResult(status=ExtractionStatus.WRITTEN, source_id="x")
    assert r._legacy_from_status() == ExtractionStatus.OK


def test_extraction_result_legacy_mapping_blocked():
    r = ExtractionResult(status=ExtractionStatus.BLOCKED, source_id="x")
    assert r._legacy_from_status() == ExtractionStatus.NEEDS_REVIEW


def test_extraction_result_legacy_mapping_failed():
    """plan §2.2.1: FAILED (technical error) maps to legacy NEEDS_REVIEW."""
    r = ExtractionResult(status=ExtractionStatus.FAILED, source_id="x")
    assert r._legacy_from_status() == ExtractionStatus.NEEDS_REVIEW


def test_extraction_result_legacy_mapping_incomplete():
    r = ExtractionResult(status=ExtractionStatus.INCOMPLETE, source_id="x")
    assert r._legacy_from_status() == ExtractionStatus.INCOMPLETE


def test_extraction_result_legacy_mapping_skipped():
    """plan §2.2.1: SKIPPED maps to legacy OK (skip-hit cache counts as
    a successful no-op for the v3 verdict)."""
    r = ExtractionResult(status=ExtractionStatus.SKIPPED, source_id="x")
    assert r._legacy_from_status() == ExtractionStatus.OK


def test_from_v3_status_ok_maps_to_written():
    r = ExtractionResult.from_v3_status(ExtractionStatus.OK, "x")
    assert r.status == ExtractionStatus.WRITTEN
    assert r.legacy_status == ExtractionStatus.OK


def test_from_v3_status_needs_review_maps_to_blocked():
    r = ExtractionResult.from_v3_status(ExtractionStatus.NEEDS_REVIEW, "x")
    assert r.status == ExtractionStatus.BLOCKED
    assert r.legacy_status == ExtractionStatus.NEEDS_REVIEW


def test_from_v3_status_incomplete_maps_to_incomplete():
    r = ExtractionResult.from_v3_status(ExtractionStatus.INCOMPLETE, "x")
    assert r.status == ExtractionStatus.INCOMPLETE
    assert r.legacy_status == ExtractionStatus.INCOMPLETE


def test_extraction_result_getitem_returns_to_dict_values():
    """__getitem__ exposes the serialized view for legacy callers."""
    r = ExtractionResult(
        status=ExtractionStatus.FAILED,
        source_id="x.md",
        review_reasons=["boom"],
    )
    assert r["status"] == "failed"
    assert r["legacy_status"] == "needs_review"
    assert r["source_id"] == "x.md"
    # Unknown keys raise KeyError (true dict semantics).
    with pytest.raises(KeyError):
        _ = r["not_a_key"]


def test_extraction_result_get_returns_default():
    r = ExtractionResult(status=ExtractionStatus.WRITTEN, source_id="x")
    assert r.get("missing", "fallback") == "fallback"
    assert r.get("source_id") == "x"


def test_extraction_result_default_fields():
    """New fields default to empty / falsy so old constructions still work."""
    r = ExtractionResult(status=ExtractionStatus.OK, source_id="x")
    assert r.source_md5 == ""
    assert r.attempts == 1
    assert r.written_page_ids == []
    assert r.blocked_page_ids == []
    assert r.failed_page_ids == []
    assert r.legacy_status is None


def test_extraction_result_metadata_merges_into_to_dict():
    """Legacy fields carried in ``metadata`` surface through ``to_dict()``
    so the pre-refactor JSON contract keeps working."""
    r = ExtractionResult(
        status=ExtractionStatus.WRITTEN,
        source_id="raw/a.md",
        metadata={
            "source": "raw/a.md",
            "characters": 1200,
            "doc_type": "single_method",
            "confidence": 0.9,
            "rationale": "ok",
            "complete": True,
            "completeness_reason": "ok",
            "topics": [{"id": "t1", "title": "Topic 1", "item_ids": ["a#section-1"]}],
            "error": None,
        },
    )
    d = r.to_dict()
    assert d["source"] == "raw/a.md"
    assert d["characters"] == 1200
    assert d["doc_type"] == "single_method"
    assert d["confidence"] == 0.9
    assert d["complete"] is True
    assert d["error"] is None
    assert d["topics"] == [
        {"id": "t1", "title": "Topic 1", "item_ids": ["a#section-1"]}
    ]
