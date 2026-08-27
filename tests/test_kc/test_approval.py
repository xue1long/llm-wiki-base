"""Tests for Approval gate (A-4 / G7, spec §5.11 + §9 I-5 + §11.4 #4).

3 TDD tests for ``src.kc.governance.approval``:

1. ``test_request_approval_creates_pending_approval`` —
   ``ApprovalGate.request_approval`` creates a pending Approval with all
   spec §5.11 mandatory fields populated (approval_id/operation/target_ids/
   proposed_event_id/status/reviewer/reason/decided_at/created_at).

2. ``test_approve_changes_status_to_approved`` —
   ``ApprovalGate.approve`` transitions pending → approved, records the
   reviewer and decided_at timestamp.

3. ``test_check_authorization_returns_false_for_unapproved_merge`` —
   spec §11.4 #4 "无审计 merge/supersede = 0" hard gate: an unapproved
   merge returns False from ``check_authorization``.

Until ``src.kc.governance.approval`` ships, every test in this file must
FAIL with ``ImportError`` or ``ModuleNotFoundError``. After A-4 ships, all 3
must pass.

Roadmap v2.2 §A-4:
    spec §5.11 — Approval dataclass
    spec §9 I-5 — 高风险写操作门禁 (merge / split / supersede / concept_identity_change)
    spec §11.4 #4 — 无审计 merge/supersede = 0
"""
from __future__ import annotations


def test_request_approval_creates_pending_approval():
    """request_approval 返回 pending Approval 且 spec §5.11 字段齐全。"""
    from src.kc.governance.approval import ApprovalGate

    gate = ApprovalGate()
    approval = gate.request_approval(
        operation="merge",
        target_ids=["slug-a", "slug-b"],
        proposed_event_id="rev_test_001",
        reviewer="dedup_auto",
        reason="high-confidence duplicate (threshold=high)",
    )

    # spec §5.11 必填字段
    assert approval.approval_id.startswith("appr_")
    assert approval.operation == "merge"
    assert list(approval.target_ids) == ["slug-a", "slug-b"]
    assert approval.proposed_event_id == "rev_test_001"
    assert approval.status == "pending"  # 必填字段
    assert approval.reviewer == "dedup_auto"
    assert approval.reason.startswith("high-confidence")
    assert approval.decided_at is None  # pending 必为 None
    assert approval.created_at > 0  # unix ms

    # gate 内部可查到
    assert gate.get_approval(approval.approval_id) is approval


def test_approve_changes_status_to_approved():
    """approve() 将 pending → approved 并记录 reviewer + decided_at。"""
    from src.kc.governance.approval import ApprovalGate

    gate = ApprovalGate()
    pending = gate.request_approval(
        operation="merge",
        target_ids=["x", "y"],
        proposed_event_id="rev_test_002",
        reviewer="dedup_auto",
    )
    assert pending.status == "pending"
    assert pending.decided_at is None

    decided = gate.approve(pending.approval_id, reviewer="human-reviewer")

    assert decided.status == "approved"
    assert decided.reviewer == "human-reviewer"  # 覆盖原 reviewer
    assert decided.decided_at is not None and decided.decided_at > 0
    assert decided.created_at == pending.created_at  # 不可变
    assert decided.approval_id == pending.approval_id
    # gate 内部状态同步更新
    assert gate.get_approval(pending.approval_id).status == "approved"


def test_check_authorization_returns_false_for_unapproved_merge():
    """spec §11.4 #4 硬门槛：无 approved approval → check_authorization False。

    防止 "无审计 merge/supersede" 出现；dedup_auto --require-approval 路径
    必须先创建 pending Approval，再由 reviewer approve 后才能执行 merge。
    """
    from src.kc.governance.approval import ApprovalGate

    gate = ApprovalGate()

    # 没有创建过 approval
    assert gate.check_authorization("merge", ["a", "b"]) is False

    # 即使创建了 pending, 没批准也不能授权
    gate.request_approval(
        operation="merge",
        target_ids=["a", "b"],
        proposed_event_id="rev_test_003",
    )
    assert gate.check_authorization("merge", ["a", "b"]) is False

    # 批准后返回 True
    gate.approve(  # noqa: F841 — 副作用: 写入 approved status
        list(gate._approvals.keys())[0], reviewer="human-reviewer"
    )
    assert gate.check_authorization("merge", ["a", "b"]) is True

    # 不同 operation 不授权
    assert gate.check_authorization("supersede", ["a", "b"]) is False
