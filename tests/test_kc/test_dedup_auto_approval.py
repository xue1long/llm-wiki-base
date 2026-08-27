"""Tests for dedup_auto dual-mode wrapper (A-4 / G7 commit 2, H-1 decision, spec §11.4 #4).

3 TDD tests for ``src.wiki.features.dedup_auto.dedup_auto_with_approval``:

1. ``test_dedup_auto_with_approval_default_preserves_legacy_behavior`` —
   ``dedup_auto_with_approval(require_approval=False)`` 默认走
   ``dedup_auto`` 既有路径 (merge-auto-high legacy, 0 regression).

2. ``test_dedup_auto_with_approval_require_approval_creates_pending_only`` —
   ``dedup_auto_with_approval(require_approval=True)`` 创建 pending
   Approval (reviewer="dedup_auto"), **不** 实际 merge, 不写
   ``.index/dedup_history/<id>/<slug>.md``, 不删 entity 文件 (spec §11.4 #4
   无审计 merge = 0 硬门槛).

3. ``test_dedup_auto_existing_tests_zero_regression`` —
   既有 ``tests/test_wiki/test_dedup_auto.py`` 2 测试
   (test_dedup_auto_records / test_dedup_auto_with_no_duplicates) 0 回归
   (H-1 决策硬要求).

Until ``src.wiki.features.dedup_auto.dedup_auto_with_approval`` ships,
test #1 / #2 must FAIL with ``AttributeError``. Test #3 is a regression
guard for existing behavior.

Roadmap v2.2 §A-4 commit 2 + H-1 decision:
    spec §11.4 #4 — 无审计 merge/supersede = 0
    H-1: --require-approval 开关（默认 False 兼容历史）
"""
from __future__ import annotations


def test_dedup_auto_with_approval_default_preserves_legacy_behavior(tmp_path):
    """默认 require_approval=False → 既有 dedup_auto 行为 (0 回归)。"""
    from src.wiki.features.dedup_auto import dedup_auto_with_approval
    from src.wiki.storage.ensure import ensure_knowledge_base
    from src.wiki.core.paths import WikiPaths
    from src.wiki.storage.page_writer import write_page
    from src.wiki.core.types import PageType, WikiPage

    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    write_page(paths, WikiPage(id="a", title="A", type=PageType.ENTITY, body="x"))

    # 既有行为：无 duplicates 时返回空 list（不创建 Approval）
    records = dedup_auto_with_approval(paths, provider=None, threshold="high")
    assert records == []


def test_dedup_auto_with_approval_require_approval_creates_pending_only(tmp_path):
    """require_approval=True → 创建 pending Approval, 不实际 merge。"""
    from src.kc.governance.approval import Approval, ApprovalGate
    from src.wiki.features.dedup_auto import dedup_auto_with_approval
    from src.wiki.features import dedup as dedup_mod
    from src.wiki.storage.ensure import ensure_knowledge_base
    from src.wiki.core.paths import WikiPaths
    from src.wiki.storage.page_writer import write_page
    from src.wiki.core.types import PageType, WikiPage

    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    # 写两个 entity page
    write_page(paths, WikiPage(id="slug-a", title="A", type=PageType.ENTITY, body="x"))
    write_page(paths, WikiPage(id="slug-b", title="B", type=PageType.ENTITY, body="y"))

    # monkey-patch find_duplicates 模拟高置信度重复 (避免依赖 LLM)
    def _fake_duplicates(paths, provider):
        return [("slug-a", "slug-b")]

    orig = dedup_mod.find_duplicates
    dedup_mod.find_duplicates = _fake_duplicates
    try:
        results = dedup_auto_with_approval(
            paths, provider=None, threshold="high", require_approval=True
        )
    finally:
        dedup_mod.find_duplicates = orig

    # 期望：返回 1 个 pending Approval（不实际合并）
    assert len(results) == 1
    approval = results[0]
    assert isinstance(approval, Approval)
    assert approval.status == "pending"
    assert approval.operation == "merge"
    assert list(approval.target_ids) == ["slug-a", "slug-b"]
    assert approval.reviewer == "dedup_auto"
    assert approval.reason.startswith("high-confidence")
    assert approval.proposed_event_id.startswith("rev_dedup_")
    assert approval.decided_at is None

    # spec §11.4 #4：ApprovalGate 内含 1 个 pending approval，**未批准**
    gate = ApprovalGate()
    # 单独创建另一个 gate 来验证 (dedup_auto_with_approval 内部已 persist)
    assert approval.approval_id.startswith("appr_")

    # spec §11.4 #4：无 approved approval → check_authorization False
    assert gate.check_authorization("merge", ["slug-a", "slug-b"]) is False

    # 关键：实体文件**未删除**（未实际 merge）
    assert (paths.wiki_entities / "slug-a.md").exists()
    assert (paths.wiki_entities / "slug-b.md").exists()

    # 关键：未创建 dedup_history 归档
    history_root = paths.root / ".index" / "dedup_history"
    # 历史归档目录存在但是空的（或者仅有 approval.jsonl 之外的目录）
    if history_root.exists():
        record_dirs = [p for p in history_root.iterdir() if p.is_dir()]
        assert record_dirs == []  # 无 merge 归档目录


def test_dedup_auto_existing_tests_zero_regression(tmp_path):
    """H-1 决策硬要求：既有 dedup_auto 测试 0 回归。

    集成式回归 guard：本测试调用 dedup_auto_with_approval 默认路径
    (require_approval=False) → 应等同 dedup_auto 行为。
    实际既有 dedup_auto 行为已由 tests/test_wiki/test_dedup_auto.py 覆盖，
    本测试仅作为 in-this-file 兜底。
    """
    from src.wiki.features.dedup_auto import dedup_auto_with_approval, dedup_auto
    from src.wiki.storage.ensure import ensure_knowledge_base
    from src.wiki.core.paths import WikiPaths

    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)

    # 默认参数走 dedup_auto 既有行为
    records_legacy = dedup_auto(paths, provider=None, threshold="high")
    records_wrapper = dedup_auto_with_approval(
        paths, provider=None, threshold="high"
    )
    assert records_wrapper == records_legacy
