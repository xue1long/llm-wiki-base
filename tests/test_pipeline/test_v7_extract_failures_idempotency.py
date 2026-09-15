"""T3 queue core: 稳定 review ID + 幂等性测试。

plan §4 Task 3 第 2 个 checkbox:
  ``enqueue_failure()`` 用 ``source + stage + page_id/topic_id + reason +
  content_hash`` 生成稳定 review ID;同一失败重跑只更新已有项,
  不产生重复审核项。

测试覆盖:
1. 同 (source, stage, page_id, topic_id, reason, content_hash) 调用两次
   → 返回相同 review_id,queue 条目数不增加(attempts=2)
2. 仅 page_id 不同 → 不同 review_id
3. 仅 reason 不同 → 不同 review_id
4. content_hash 空 vs 非空 → 不同 review_id(若 reason 同)
5. last_seen_at 在第二次调用时更新(时间差 > 0)
6. queue_path 显式传入自定义路径 → 写到该路径(不写 CWD)
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from src.pipeline.v7_extract.failures import (
    _read_queue,
    enqueue_failure,
)


# ---------------------------------------------------------------------------
# 1. 同 (source, stage, page_id, topic_id, reason, content_hash) 调用两次
#    → 返回相同 review_id,queue 条目数不增加(attempts=2)
# ---------------------------------------------------------------------------

def test_idempotent_same_args_returns_same_review_id(tmp_path):
    """稳定 ID: 同输入两次调用 → 返回相同 review_id,queue 中只有 1 条。"""
    path = tmp_path / "reviews_queue.json"
    common = dict(
        source_id="raw/source_a.md",
        stage="stage5",
        page_id="48d50307-writing-techniques",
        topic_id="writing-techniques",
        reason="evidence_failed",
        content_hash="abc123",
    )
    rid1 = enqueue_failure(queue_path=path, **common)
    rid2 = enqueue_failure(queue_path=path, **common)
    assert rid1 == rid2
    assert rid1.startswith("v7fail-")

    items = _read_queue(path)
    assert len(items) == 1, "同输入不应新增条目"
    item = items[0]
    assert item["id"] == rid1
    assert item["attempts"] == 2, "第二次调用应使 attempts 累加到 2"


# ---------------------------------------------------------------------------
# 2. 仅 page_id 不同 → 不同 review_id
# ---------------------------------------------------------------------------

def test_different_page_id_produces_different_review_id(tmp_path):
    """page_id 是身份字段的一部分;不同 page_id 必须产出不同 review_id。"""
    path = tmp_path / "reviews_queue.json"
    rid_a = enqueue_failure(
        source_id="raw/source_a.md",
        stage="stage5",
        page_id="48d50307-writing-techniques",
        topic_id="writing-techniques",
        reason="evidence_failed",
        content_hash="abc123",
        queue_path=path,
    )
    rid_b = enqueue_failure(
        source_id="raw/source_a.md",
        stage="stage5",
        page_id="48d50307-opening-hooks",
        topic_id="opening-hooks",
        reason="evidence_failed",
        content_hash="abc123",
        queue_path=path,
    )
    assert rid_a != rid_b
    items = _read_queue(path)
    assert len(items) == 2


# ---------------------------------------------------------------------------
# 3. 仅 reason 不同 → 不同 review_id
# ---------------------------------------------------------------------------

def test_different_reason_produces_different_review_id(tmp_path):
    """reason 是身份字段的一部分;不同 reason 必须产出不同 review_id。"""
    path = tmp_path / "reviews_queue.json"
    rid1 = enqueue_failure(
        source_id="raw/source_a.md",
        stage="stage5",
        page_id="48d50307-writing-techniques",
        topic_id="writing-techniques",
        reason="evidence_failed",
        queue_path=path,
    )
    rid2 = enqueue_failure(
        source_id="raw/source_a.md",
        stage="stage5",
        page_id="48d50307-writing-techniques",
        topic_id="writing-techniques",
        reason="schema_invalid",
        queue_path=path,
    )
    assert rid1 != rid2
    items = _read_queue(path)
    assert len(items) == 2


# ---------------------------------------------------------------------------
# 4. content_hash 空 vs 非空 → 不同 review_id(若 reason 同)
# ---------------------------------------------------------------------------

def test_empty_vs_nonempty_content_hash_produces_different_review_id(tmp_path):
    """content_hash 是身份字段的一部分;空 vs 非空 → 不同 review_id。"""
    path = tmp_path / "reviews_queue.json"
    rid_empty = enqueue_failure(
        source_id="raw/source_a.md",
        stage="stage5",
        page_id="48d50307-writing-techniques",
        topic_id="writing-techniques",
        reason="evidence_failed",
        content_hash="",
        queue_path=path,
    )
    rid_hash = enqueue_failure(
        source_id="raw/source_a.md",
        stage="stage5",
        page_id="48d50307-writing-techniques",
        topic_id="writing-techniques",
        reason="evidence_failed",
        content_hash="abc123",
        queue_path=path,
    )
    assert rid_empty != rid_hash
    items = _read_queue(path)
    assert len(items) == 2


# ---------------------------------------------------------------------------
# 5. last_seen_at 在第二次调用时更新(时间差 > 0)
# ---------------------------------------------------------------------------

def test_last_seen_at_updates_on_second_call(tmp_path):
    """同输入第二次调用时,last_seen_at 必须晚于首次的 created_at。"""
    path = tmp_path / "reviews_queue.json"
    enqueue_failure(
        source_id="raw/source_a.md",
        stage="stage5",
        page_id="48d50307-writing-techniques",
        topic_id="writing-techniques",
        reason="evidence_failed",
        content_hash="abc123",
        queue_path=path,
    )
    # Sleep 5 ms so the now_ms() resolution (ms) can detect a strict increase
    time.sleep(0.005)
    enqueue_failure(
        source_id="raw/source_a.md",
        stage="stage5",
        page_id="48d50307-writing-techniques",
        topic_id="writing-techniques",
        reason="evidence_failed",
        content_hash="abc123",
        queue_path=path,
    )

    items = _read_queue(path)
    assert len(items) == 1
    item = items[0]
    created_at = item["created_at"]
    last_seen_at = item["last_seen_at"]
    assert last_seen_at > created_at, (
        f"last_seen_at ({last_seen_at}) must be strictly greater than "
        f"created_at ({created_at}) after second call"
    )


# ---------------------------------------------------------------------------
# 6. queue_path 显式传入自定义路径 → 写到该路径(不写 CWD)
# ---------------------------------------------------------------------------

def test_explicit_queue_path_does_not_write_to_cwd(tmp_path, monkeypatch):
    """显式传 queue_path 时,queue 文件不应落 CWD(默认 _DEFAULT_QUEUE_PATH)。"""
    monkeypatch.chdir(tmp_path)
    custom_path = tmp_path / "custom_root" / "reviews_queue.json"
    rid = enqueue_failure(
        source_id="raw/source_a.md",
        stage="stage5",
        page_id="48d50307-writing-techniques",
        topic_id="writing-techniques",
        reason="evidence_failed",
        queue_path=custom_path,
    )
    # 自定义路径被写入
    assert custom_path.exists()
    items = _read_queue(custom_path)
    assert len(items) == 1
    assert items[0]["id"] == rid

    # CWD 下不存在默认路径文件
    default_path = Path(".index") / "reviews_queue.json"
    cwd_default = tmp_path / ".index" / "reviews_queue.json"
    assert not cwd_default.exists(), (
        "显式传 queue_path 时不应在 CWD 落默认 queue 文件"
    )


# ---------------------------------------------------------------------------
# 额外:验证 ID 算法稳定性(同一字符串两次 → 同 ID)
# ---------------------------------------------------------------------------

def test_review_id_format_is_stable_sha1_prefix(tmp_path):
    """review_id 必须是 ``v7fail-`` + 12 hex chars(0-9a-f)。"""
    path = tmp_path / "reviews_queue.json"
    rid = enqueue_failure(
        source_id="raw/source_a.md",
        stage="stage5",
        page_id="48d50307-writing-techniques",
        topic_id="writing-techniques",
        reason="evidence_failed",
        content_hash="abc123",
        queue_path=path,
    )
    assert rid.startswith("v7fail-")
    suffix = rid[len("v7fail-"):]
    assert len(suffix) == 12
    int(suffix, 16)  # must be valid hex
