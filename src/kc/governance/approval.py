"""Approval gate (A-4 / G7, spec §5.11 + §9 I-5 + §11.4 #4).

Implements:
    - ``Approval``: spec §5.11 Approval dataclass
        approval_id / operation / target_ids / proposed_event_id /
        status / reviewer / reason / decided_at / created_at
    - ``ApprovalGate``: 高风险写操作门禁 (merge / split / supersede /
      concept_identity_change) — spec §9 I-5
    - spec §11.4 #4: 无审计 merge/supersede = 0
        ``check_authorization`` 是 release-time 硬门槛, 未批准的 merge /
        split / supersede / identity_change 一律拒绝

Persistence: ``ApprovalGate.persist_approvals`` 写 append-only JSONL 到
``.index/approvals.jsonl`` (spec §3.3 raw source 只读精神: append-only 是
唯一的写入模式)。
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


# spec §5.11 字面量类型
ApprovalOperation = Literal["merge", "split", "supersede", "concept_identity_change"]
ApprovalStatus = Literal["pending", "approved", "rejected"]


@dataclass(frozen=True)
class Approval:
    """spec §5.11 Approval dataclass — 高风险写操作审计记录。"""

    approval_id: str
    operation: ApprovalOperation
    target_ids: tuple[str, ...]
    proposed_event_id: str
    status: ApprovalStatus = "pending"
    reviewer: str | None = None
    reason: str = ""
    decided_at: int | None = None
    created_at: int = 0


class ApprovalGate:
    """高风险写操作门禁（spec §5.11 + §9 I-5 + §11.4 #4）。

    所有 merge / split / supersede / concept_identity_change 操作必须先创建
    pending approval, 经 reviewer approve 后才能执行 (release-time 硬门槛)。

    实例生命周期建议：每条 dedup/merge 流程创建独立 ``ApprovalGate``，
    ``request_approval`` + ``approve`` 在同一调用栈内完成, 持久化在最后
    ``persist_approvals(project_root)`` 一次性 append-only 写出。
    """

    def __init__(self):
        self._approvals: dict[str, Approval] = {}

    def request_approval(
        self,
        operation: ApprovalOperation,
        target_ids: list[str],
        proposed_event_id: str,
        reviewer: str | None = None,
        reason: str = "",
    ) -> Approval:
        """创建 pending approval（spec §11.4 #4 高风险写操作必填）。"""
        if not target_ids:
            raise ValueError("target_ids 不能为空")
        if not proposed_event_id:
            raise ValueError("proposed_event_id 不能为空")

        approval_id = f"appr_{uuid.uuid4().hex[:12]}"
        approval = Approval(
            approval_id=approval_id,
            operation=operation,
            target_ids=tuple(target_ids),
            proposed_event_id=proposed_event_id,
            status="pending",
            reviewer=reviewer,
            reason=reason,
            decided_at=None,
            created_at=int(time.time() * 1000),
        )
        self._approvals[approval_id] = approval
        return approval

    def approve(self, approval_id: str, reviewer: str) -> Approval:
        """批准 pending → approved (spec §5.11 status transition)。

        冻结字段保留: approval_id / operation / target_ids /
        proposed_event_id / reason / created_at; 覆盖 status / reviewer /
        decided_at。
        """
        if not reviewer:
            raise ValueError("reviewer 不能为空")

        old = self._approvals.get(approval_id)
        if old is None:
            raise KeyError(f"approval_id 不存在: {approval_id}")
        if old.status != "pending":
            raise ValueError(
                f"approval status 必须为 pending（实际: {old.status}）"
            )

        new = Approval(
            approval_id=old.approval_id,
            operation=old.operation,
            target_ids=old.target_ids,
            proposed_event_id=old.proposed_event_id,
            status="approved",
            reviewer=reviewer,
            reason=old.reason,
            decided_at=int(time.time() * 1000),
            created_at=old.created_at,
        )
        self._approvals[approval_id] = new
        return new

    def reject(self, approval_id: str, reviewer: str, reason: str) -> Approval:
        """拒绝 pending → rejected (spec §5.11 status transition)。"""
        if not reviewer:
            raise ValueError("reviewer 不能为空")
        if not reason:
            raise ValueError("reject reason 不能为空")

        old = self._approvals.get(approval_id)
        if old is None:
            raise KeyError(f"approval_id 不存在: {approval_id}")
        if old.status != "pending":
            raise ValueError(
                f"approval status 必须为 pending（实际: {old.status}）"
            )

        new = Approval(
            approval_id=old.approval_id,
            operation=old.operation,
            target_ids=old.target_ids,
            proposed_event_id=old.proposed_event_id,
            status="rejected",
            reviewer=reviewer,
            reason=reason,
            decided_at=int(time.time() * 1000),
            created_at=old.created_at,
        )
        self._approvals[approval_id] = new
        return new

    def check_authorization(
        self, operation: ApprovalOperation, target_ids: list[str]
    ) -> bool:
        """spec §11.4 #4: 检查高风险写操作是否有 approved approval。

        返回 True 当且仅当：存在一个 ``approved`` 状态 approval,
        其 ``operation == operation`` 且 ``target_ids`` 与请求一致
        (顺序无关, set 比较)。

        这条是 release-time 硬门槛 — 没有 approved approval, merge / split /
        supersede / concept_identity_change 一律被 ``check_authorization``
        拒绝, 配合上层 ``if not gate.check_authorization(...): raise`` 即可
        保证 "无审计 merge/supersede = 0"。
        """
        target_set = set(target_ids)
        for approval in self._approvals.values():
            if (
                approval.status == "approved"
                and approval.operation == operation
                and set(approval.target_ids) == target_set
            ):
                return True
        return False

    def persist_approvals(self, project_root: Path) -> Path:
        """append-only JSONL 写入 ``.index/approvals.jsonl`` (spec §3.3)。"""
        approvals_log = project_root / ".index" / "approvals.jsonl"
        approvals_log.parent.mkdir(parents=True, exist_ok=True)

        with approvals_log.open("a", encoding="utf-8") as f:
            for approval in self._approvals.values():
                payload = {
                    "approval_id": approval.approval_id,
                    "operation": approval.operation,
                    "target_ids": list(approval.target_ids),
                    "proposed_event_id": approval.proposed_event_id,
                    "status": approval.status,
                    "reviewer": approval.reviewer,
                    "reason": approval.reason,
                    "decided_at": approval.decided_at,
                    "created_at": approval.created_at,
                }
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return approvals_log

    def get_approval(self, approval_id: str) -> Approval | None:
        """查 approval (供测试 / 调用方使用)。"""
        return self._approvals.get(approval_id)
