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
    assert review_id.startswith("v7-")

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
    enqueue_failure("a", "stage1", "r1", queue_path=path)
    enqueue_failure("b", "stage5", "r2", queue_path=path)
    enqueue_failure("c", "stage3", "r3", queue_path=path)
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
