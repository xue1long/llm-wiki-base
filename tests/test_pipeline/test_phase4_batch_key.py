"""P1（phase4_batch.py:743 根因修复）— batch_key 必须绑定 manifest。

Bug：``batch_key = f"batch_{args.batch}"`` 不绑定 manifest，导致不同
manifest（reingest_plan.json / 01_新手入门 专用 manifest）同批次号互相覆盖
状态键，--resume 会错误复用别的 manifest 的 completed_files。

修复后的契约（TDD 红→绿）：
  * 默认 manifest（reingest_backlog.json）→ 保持旧键 ``batch_{batch}``，
    以兼容 phase3_accept（读 ``batch_0``）与已落盘的 batch_2..7 条目。
  * 非默认 manifest → ``batch_{stem}_{batch}`` 绑定键，确保不同 manifest
    同批号互不碰撞。
  * ``_resolve_batch_entry(state, manifest, batch)`` 先查绑定键，再回退旧键
    ``batch_{batch}``（迁移防御），保证 --resume 既隔离不同 manifest，又
    不破坏已完成批次的可续跑性。
"""
from __future__ import annotations

import scripts.phase4_batch as p4


# 默认 manifest（与 phase4_batch.MANIFEST 同文件）
BACKLOG = "knowledge/novel-wiki/.index/reingest_backlog.json"
# 非默认 manifest
PLAN = "knowledge/novel-wiki/.index/reingest_plan.json"
NOVICE = "knowledge/novel-wiki/.index/01_新手入门_manifest.json"


def test_batch_key_default_manifest_uses_legacy_format():
    """默认 manifest 保持旧键，保 phase3_accept 兼容、与既有条目一致。"""
    assert p4._batch_key(BACKLOG, 0) == "batch_0"
    assert p4._batch_key(BACKLOG, 3) == "batch_3"


def test_batch_key_alternate_manifest_is_stem_bound():
    """非默认 manifest → 绑定键，形式稳定可预期。"""
    assert p4._batch_key(PLAN, 0) == "batch_reingest_plan_0"
    assert p4._batch_key(NOVICE, 0) == "batch_01_新手入门_manifest_0"


def test_batch_key_distinct_across_manifests_and_batches():
    """同批号跨 manifest 不碰撞；同 manifest 跨批号也不碰撞。"""
    # 跨 manifest（默认 vs 两个非默认）
    assert p4._batch_key(PLAN, 0) != p4._batch_key(BACKLOG, 0)
    assert p4._batch_key(PLAN, 0) != p4._batch_key(NOVICE, 0)
    assert p4._batch_key(BACKLOG, 0) != p4._batch_key(NOVICE, 0)
    # 同 manifest 跨批号
    assert p4._batch_key(PLAN, 0) != p4._batch_key(PLAN, 1)


def test_resolve_batch_entry_isolates_different_manifests():
    """默认 manifest 走旧键、非默认走绑定键，同号批次各自独立、不串味。"""
    state = {
        "batch_2": {"status": "committed", "completed_files": ["backlog_only.md"]},
        "batch_reingest_plan_2": {
            "status": "committed", "completed_files": ["plan_only.md"],
        },
    }
    a = p4._resolve_batch_entry(state, PLAN, 2)
    b = p4._resolve_batch_entry(state, BACKLOG, 2)

    assert a["completed_files"] == ["plan_only.md"]
    assert b["completed_files"] == ["backlog_only.md"]


def test_resolve_batch_entry_falls_back_to_legacy_key():
    """非默认 manifest 下，旧键 ``batch_{batch}`` 仍可被解析（迁移防御）。"""
    state = {"batch_2": {"status": "committed", "completed_files": ["legacy.md"]}}
    entry = p4._resolve_batch_entry(state, PLAN, 2)
    assert entry["completed_files"] == ["legacy.md"]


def test_resolve_batch_entry_new_key_wins_over_legacy():
    """绑定键存在时优先绑定键（旧键视为过期、被覆盖）。"""
    state = {
        "batch_reingest_plan_2": {"completed_files": ["new.md"]},
        "batch_2": {"completed_files": ["stale.md"]},
    }
    entry = p4._resolve_batch_entry(state, PLAN, 2)
    assert entry["completed_files"] == ["new.md"]


def test_resolve_batch_entry_missing_returns_none():
    """无任何匹配键 → 返回 None（fresh run）。"""
    assert p4._resolve_batch_entry({}, PLAN, 9) is None
