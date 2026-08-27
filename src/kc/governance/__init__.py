"""Governance: Approval gate for high-risk write operations (A-4 / G7, spec §5.11 + §11.4 #4).

Provides:
    - Approval: spec §5.11 Approval dataclass
    - ApprovalGate: spec §11.4 #4 高风险写操作门禁
      (merge / split / supersede / concept_identity_change)
    - ApprovalOperation / ApprovalStatus: Literal type aliases

Append-only JSONL persistence via ``ApprovalGate.persist_approvals`` writes
``.index/approvals.jsonl`` (spec §3.3 raw source 只读精神).
"""
from .approval import Approval, ApprovalGate, ApprovalOperation, ApprovalStatus

__all__ = ["Approval", "ApprovalGate", "ApprovalOperation", "ApprovalStatus"]
