"""Auto-merge high-confidence duplicate entity pages (--auto flag)."""
import json
import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from ..storage.page_writer import read_page, page_path_for
from ..core.types import PageType
from ..core.paths import WikiPaths
from ...lib.write_hooks import safe_write, DELETE_SENTINEL


_logger = logging.getLogger(__name__)


HISTORY_DIR = ".index/dedup_history"
RETENTION_DAYS = 30


@dataclass
class DedupMergeRecord:
    id: str
    canonical_slug: str
    merged_slugs: list[str]
    confidence: str
    merged_at: int
    archive_dir: Path


class DedupHistoryStore:
    @staticmethod
    def record(paths: WikiPaths, canonical: str, merged: list[str], confidence: str) -> DedupMergeRecord:
        history_root = paths.root / HISTORY_DIR
        history_root.mkdir(parents=True, exist_ok=True)
        record_id = str(uuid.uuid4())[:8]
        record_dir = history_root / record_id
        record_dir.mkdir(parents=True, exist_ok=True)
        for slug in merged:
            src = page_path_for(paths, PageType.ENTITY, slug)
            if src.exists():
                content = src.read_text(encoding="utf-8")
                (record_dir / f"{slug}.md").write_text(content, encoding="utf-8")
                # Use safe_write so the deletion is deferred when called inside
                # an AtomicContext (atomic, batched commit).
                safe_write(src, DELETE_SENTINEL)
        record = DedupMergeRecord(
            id=record_id, canonical_slug=canonical, merged_slugs=merged,
            confidence=confidence, merged_at=int(time.time() * 1000), archive_dir=record_dir,
        )
        (history_root / f"{record_id}.json").write_text(json.dumps({
            "id": record_id, "canonical_slug": canonical, "merged_slugs": merged,
            "confidence": confidence, "merged_at": record.merged_at,
        }, indent=2), encoding="utf-8")
        return record


def dedup_auto(paths: WikiPaths, provider, threshold: str = "high") -> list[DedupMergeRecord]:
    """Auto-merge high-confidence duplicates. Returns list of merge records.

    High-confidence (slug match / title similarity) → auto-merge.
    Medium-confidence (vector similarity) → review items.
    """
    from .dedup import find_duplicates, find_near_duplicates

    records: list[DedupMergeRecord] = []

    # High confidence: auto-merge
    duplicates = find_duplicates(paths, provider)
    for slug_a, slug_b in duplicates:
        records.append(DedupHistoryStore.record(paths, slug_a, [slug_b], "high"))

    # Medium confidence: create review items
    if threshold in ("medium", "low"):
        near = find_near_duplicates(paths, provider)
        if near:
            from .review import add_review
            import time
            for slug_a, slug_b, confidence in near:
                try:
                    page_a = read_page((paths.wiki_entities / f"{slug_a}.md"))
                    page_b = read_page((paths.wiki_entities / f"{slug_b}.md"))
                except Exception:
                    continue
                add_review(
                    paths,
                    type="duplicate-page",
                    title=f"{page_a.title} ≈ {page_b.title}",
                    detail=f"Vector similarity {confidence:.2f} between entity pages '{slug_a}' and '{slug_b}'.",
                    confidence=confidence,
                    page_path=str(paths.wiki_entities / f"{slug_a}.md"),
                    created_at=int(time.time() * 1000),
                )

    return records


# === A-4 / G7 commit 2 — dedup_auto dual-mode wrapper ========================
#
# H-1 决策: --require-approval 开关（默认 False 兼容历史）
# spec §11.4 #4 硬门槛: 无审计 merge/supersede = 0
#
# require_approval=False → merge-auto-high legacy（既有 dedup_auto 行为, 0 回归）
# require_approval=True  → merge-reviewed (创建 pending Approval, 不实际 merge,
#                          等 reviewer approve 后由人工流程执行)

def dedup_auto_with_approval(
    paths: WikiPaths,
    provider,
    threshold: str = "high",
    require_approval: bool = False,
) -> "list[DedupMergeRecord | object]":
    """dedup_auto 双模式 wrapper（H-1 决策, A-4 / G7 commit 2）。

    Args:
        paths: WikiPaths（项目 wiki 路径）
        provider: LLM provider（deduplication 用, 可为 None）
        threshold: "high" / "medium" / "low"（spec §5.11 高/中/低置信度）
        require_approval: H-1 决策开关
            - False（默认）: merge-auto-high legacy, 直接调用 dedup_auto
              既有路径. 保持向后兼容.
            - True: merge-reviewed 模式 (spec §11.4 #4 强制). 创建 pending
              Approval, **不** 实际 merge, 不删 entity 文件, 不写
              dedup_history. Reviewer 调用 ``ApprovalGate.approve`` 后再
              走人工 merge 流程.

    Returns:
        - require_approval=False: list[DedupMergeRecord] (dedup_auto 既有返回)
        - require_approval=True:  list[Approval] (pending, 长度 = 找到的
          高置信度重复对数)

    spec §11.4 #4: 无审计 merge/supersede = 0 — 该函数 require_approval=True
    路径保证所有 merge 操作都有对应 Approval 审计记录, 且未批准的 merge
    不会被自动执行。
    """
    if not require_approval:
        # H-1 决策：默认走 legacy merge-auto-high（0 回归）
        return dedup_auto(paths, provider, threshold)

    # spec §11.4 #4 强制路径：merge-reviewed
    # Step 1: 找高置信度重复（既有 find_duplicates, 不修改既有逻辑）
    from .dedup import find_duplicates
    from ...kc.governance.approval import ApprovalGate

    gate = ApprovalGate()
    pending_approvals: list[object] = []

    duplicates = find_duplicates(paths, provider)
    for slug_a, slug_b in duplicates:
        # Step 2: 创建 pending Approval（**不**实际合并）
        approval = gate.request_approval(
            operation="merge",
            target_ids=[slug_a, slug_b],
            proposed_event_id=f"rev_dedup_{uuid.uuid4().hex[:12]}",
            reviewer="dedup_auto",
            reason=f"high-confidence duplicate (threshold={threshold})",
        )
        pending_approvals.append(approval)

    # Step 3: persist append-only (spec §3.3 raw source 只读精神)
    if pending_approvals:
        gate.persist_approvals(paths.root)

    return pending_approvals
