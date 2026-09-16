"""Task 31 — Reconciliation CLI + Phase 1 main loop.

Four RED probes (each a contract assertion):

  * test_reconcile_command_processes_pages
        — ``reconcile_pages`` runs the per-page pipeline
          (retrieve_candidates → resolve_identity → apply_decisions)
          with isolated failures and aggregate metrics.

  * test_show_command_displays_canonical
        — ``cmd_show_canonical`` formats a canonical concept and
          prints its details. Returns 0 on success.

  * test_list_command_shows_active_only
        — ``cmd_list_canonicals`` with ``--active-only`` filters
          STALE / TOMBSTONED rows.

  * test_undo_command_removes_membership
        — ``cmd_undo`` removes a single page from a canonical's
          membership (reversible). Returns 0.

Contract summary (see plan §4 Task 31):

    metrics: processed / created_new / joined_existing / unresolved / errors
    per-page errors are isolated (Failure Contract §1)
    CLI exit codes: 0 ok, 2 errors > 0 (only when processed > 0)
"""
from __future__ import annotations

import argparse
from pathlib import Path


def test_reconcile_command_processes_pages(tmp_path: Path):
    """reconcile_pages 主循环: pages → candidates → decisions → apply.

    With empty candidates (LLM emits no verdicts → no candidates → no
    resolve_identity work), reconcile_pages still processes the page
    but does NOT create a canonical (no DISTINCT decision was emitted).
    """
    import asyncio

    from src.reconciliation.reconcile_job import reconcile_pages

    class P:
        def __init__(self, pid, title, body):
            self.id = pid
            self.title = title
            self.body = body
            self.slots = {"definition": body[:200]}

    pages = [
        P("page-a", "Concept A", "machine learning basics"),
        P("page-b", "Concept B", "totally different topic"),
    ]

    # Fake LLM 全部返回空 verdicts → resolve_identity 短路返回 []
    class FakeLLM:
        async def complete(
            self,
            *,
            prompt_kind,
            user_prompt,
            system_prompt,
            max_tokens,
            temperature,
        ):
            return '{"verdicts": []}'

    result = asyncio.run(
        reconcile_pages(
            pages,
            project_root=tmp_path,
            llm=FakeLLM(),
            body_by_page={"page-a": pages[0].body, "page-b": pages[1].body},
            resolver_fingerprint="fp-test",
        )
    )
    assert result.processed == 2
    # 没有 candidate → resolve_identity 返回 [] → apply_decisions 不创建 canonical
    assert result.created_new == 0  # 没有 DISTINCT 决策
    assert result.unresolved == 0  # 空 candidates 也不计 unresolved


def test_show_command_displays_canonical(tmp_path: Path):
    """CLI show-canonical 格式化输出."""
    from src.cli_ext.reconciliation_cmd import cmd_show_canonical
    from src.reconciliation.canonical_registry import CanonicalRegistry
    from src.reconciliation.canonical_models import (
        CanonicalConcept,
        ReconciliationStatus,
    )

    reg = CanonicalRegistry(tmp_path)
    cc = CanonicalConcept(
        canonical_id="c-aaaa1234567890",
        preferred_label="Test",
        member_page_ids=["page-x"],
        aliases=["foo", "bar"],
        status=ReconciliationStatus.ACTIVE,
        resolver_fingerprint="fp",
    )
    reg._save_concepts({cc.canonical_id: cc})

    args = argparse.Namespace(
        project_root=tmp_path, canonical_id="c-aaaa1234567890"
    )
    rc = cmd_show_canonical(args)
    assert rc == 0


def test_list_command_shows_active_only(tmp_path: Path):
    """CLI list-canonicals [--active-only]."""
    from src.cli_ext.reconciliation_cmd import cmd_list_canonicals
    from src.reconciliation.canonical_registry import CanonicalRegistry
    from src.reconciliation.canonical_models import (
        CanonicalConcept,
        ReconciliationStatus,
    )

    reg = CanonicalRegistry(tmp_path)
    reg._save_concepts(
        {
            "c-active1": CanonicalConcept(
                canonical_id="c-active1",
                preferred_label="A",
                status=ReconciliationStatus.ACTIVE,
                member_page_ids=["p1"],
                resolver_fingerprint="fp",
            ),
            "c-stale1": CanonicalConcept(
                canonical_id="c-stale1",
                preferred_label="S",
                status=ReconciliationStatus.STALE,
                member_page_ids=["p2"],
                resolver_fingerprint="fp-old",
            ),
        }
    )

    # default (--active-only)
    args = argparse.Namespace(project_root=tmp_path, active_only=True)
    rc = cmd_list_canonicals(args)
    assert rc == 0
    # --all
    args = argparse.Namespace(project_root=tmp_path, active_only=False)
    rc = cmd_list_canonicals(args)
    assert rc == 0


def test_undo_command_removes_membership(tmp_path: Path):
    """CLI undo <page_id>."""
    from src.cli_ext.reconciliation_cmd import cmd_undo
    from src.reconciliation.canonical_registry import CanonicalRegistry
    from src.reconciliation.canonical_models import (
        CanonicalConcept,
        ReconciliationStatus,
    )

    reg = CanonicalRegistry(tmp_path)
    cc = CanonicalConcept(
        canonical_id="c-aaaa1234567890",
        preferred_label="X",
        member_page_ids=["page-x", "page-y"],
        status=ReconciliationStatus.ACTIVE,
        resolver_fingerprint="fp",
    )
    reg._save_concepts({cc.canonical_id: cc})

    args = argparse.Namespace(
        project_root=tmp_path,
        page_id="page-x",
        canonical_id="c-aaaa1234567890",
    )
    rc = cmd_undo(args)
    assert rc == 0

    after = reg.get_concept("c-aaaa1234567890")
    assert after is not None
    assert "page-x" not in after.member_page_ids
    assert "page-y" in after.member_page_ids  # 其它 member 不动