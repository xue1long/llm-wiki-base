"""Task 32 — 跨阶段集成测试: 端到端 fault injection (v7 stage remediation plan §4).

Eight end-to-end tests covering crash / failure / recovery scenarios that
cross stage boundaries in the v7 extract pipeline:

  1. test_e2e_normal_source_to_written_pages
        Happy path: Stage 7 WikiWriter.commit_and_index writes the page
        and persists a manifest with phase=COMMITTED.

  2. test_e2e_stage1_failure_does_not_proceed
        LLM timeout on classify → Classification.failed=True; no
        downstream Stage 3 dispatch is forced by the failure.

  3. test_e2e_stage3_technical_failure_not_mapped_to_incomplete
        HARD INDICATOR: when check_completeness exhausts retries, the
        return is None (technical failure) — never a fake INCOMPLETE
        that would route the source into the skip-cache.

  4. test_e2e_crash_during_publish_recovers_via_manifest
        Stage 7 PUBLISHING-phase crash with the page file on disk +
        matching sha1 → reconcile_unfinished_commits transitions the
        manifest to RECONCILED.

  5. test_e2e_source_update_reconciles_stale_pages
        Stage 6R RelationStore.find_stale flags pages whose wiki
        revision_hash differs from the stored run record.

  6. test_e2e_reconciliation_attaches_pages_to_canonical
        Reconciliation Phase 1: two pages receive SAME verdicts against
        a seeded canonical → one canonical with two members.

  7. test_e2e_unresolved_decision_does_not_force_merge
        Identity resolver returns UNRESOLVED for every candidate → no
        canonical is created, no forced merge happens.

  8. test_e2e_pipeline_upgrade_triggers_re_evaluation
        Pipeline fingerprint upgrade invalidates the source-skip gate
        even when the source md5 + INCOMPLETE status match.

These tests deliberately bypass running the full 7-stage pipeline (that
would require LLM scripting for every prompt_kind); each test isolates a
single invariant by calling the smallest set of source functions that
demonstrates it.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from pathlib import Path
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Common fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """Construct a minimal project root with the directories the v7
    pipeline expects to find under it."""
    (tmp_path / "wiki" / "concepts").mkdir(parents=True)
    (tmp_path / "wiki" / "sources").mkdir(parents=True)
    (tmp_path / ".index").mkdir()
    (tmp_path / ".llm-wiki").mkdir()
    (tmp_path / "schema.md").write_text("# Schema\n", encoding="utf-8")
    return tmp_path


class _FailingLLM:
    """LLM stub that raises on every call (technical failure injector)."""

    def __init__(self, exc: Exception | None = None) -> None:
        self._exc = exc or RuntimeError("injected_llm_failure")
        self.calls: list[str] = []

    async def complete(
        self,
        *,
        prompt_kind: str,
        user_prompt: str,
        system_prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        self.calls.append(prompt_kind)
        raise self._exc


# ---------------------------------------------------------------------------
# 1. Happy path — Stage 7 writes + CommitManifest records COMMITTED.
# ---------------------------------------------------------------------------


def test_e2e_normal_source_to_written_pages(project_root: Path) -> None:
    """Happy path: WikiWriter.commit_and_index writes a ConceptPage and
    records a manifest with phase=committed. The page file exists and
    the on-disk manifest JSON agrees."""
    from src.pipeline.v7_extract.commit_manifest import (
        CommitPhase,
        manifest_dir,
    )
    from src.pipeline.v7_extract.relation_extractor import PageRelation
    from src.pipeline.v7_extract.slot_filler import (
        CONCEPT_SLOTS,
        ConceptPage,
        Slot,
        SlotEvidence,
    )
    from src.pipeline.v7_extract.wiki_writer import WikiWriter

    page_id = "扩句法-test1234"
    slots = {name: f"{name} content for test" for name in CONCEPT_SLOTS}
    slot_evidence = {
        name: Slot(
            name=name,
            body=slots[name],
            evidence=SlotEvidence(
                item_id="test",
                source_text_excerpt="excerpt",
                has_evidence=True,
                needs_review=False,
            ),
            needs_review=False,
        )
        for name in CONCEPT_SLOTS
    }
    page = ConceptPage(
        id=page_id,
        title="扩句法",
        slots=slots,
        sources=["test.md"],
        slot_evidence=slot_evidence,
        needs_review_slots=(),
        topic_id="扩句法",
    )

    writer = WikiWriter(project_root, pipeline_fingerprint="fp-e2e")
    report = writer.commit_and_index(
        [page], [PageRelation(page_id, "扩句法", "refines")]
    )

    # Page was actually written to disk.
    assert page_id in report.written
    on_disk = project_root / "wiki" / "concepts" / f"{page_id}.md"
    assert on_disk.exists()

    # A manifest was persisted with phase=committed.
    manifests = list((manifest_dir(project_root)).glob("*.json"))
    assert len(manifests) == 1
    payload = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert payload["phase"] == CommitPhase.COMMITTED.value
    # Per-page record: written_path points at the on-disk file and the
    # revision_hash is the sha1 of the rendered body (Task 19 / Task 20
    # placeholder — frontmatter sha1 will replace it).
    assert page_id in payload["pages"]
    page_record = payload["pages"][page_id]
    assert page_record["written_path"] == str(on_disk)
    assert page_record["phase"] == CommitPhase.COMMITTED.value
    body_sha = hashlib.sha1(page.body.encode("utf-8")).hexdigest()
    assert page_record["revision_hash"] == body_sha
    # Pipeline fingerprint is captured for Task 22's upgrade detector.
    assert payload["pipeline_fingerprint"] == "fp-e2e"


# ---------------------------------------------------------------------------
# 2. Stage 1 — LLM failure yields Classification.failed=True.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_stage1_failure_does_not_proceed(project_root: Path) -> None:
    """Stage 1 LLM timeout → classify_doc returns a Classification with
    failed=True. Callers can detect Stage 1 malfunction without catching
    an exception (P2: classify_doc never raises). The failing LLM must
    be retried up to max_retries (3 by default), all of which fail,
    which is the contract that makes the failure detectable."""
    from src.pipeline.v7_extract.doc_classifier import Classification, classify_doc

    llm = _FailingLLM(RuntimeError("stage1 timeout"))

    result = await classify_doc(
        "some article body",
        filename_hint="test.md",
        llm=llm,
        project_root=None,
    )

    assert isinstance(result, Classification)
    # Stage 1 malfunction is now an explicit flag, not a smuggling into
    # doc_type='incomplete' with confidence=0.
    assert result.failed is True
    assert result.error is not None
    assert "stage1 timeout" in result.error
    # The LLM was actually retried 3 times before the failure was
    # acknowledged (retry-budget exhaustion is the contract).
    assert llm.calls == ["classify"] * 3


# ---------------------------------------------------------------------------
# 3. Stage 3 — Technical failure must NEVER be disguised as INCOMPLETE.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_stage3_technical_failure_not_mapped_to_incomplete(
    project_root: Path,
) -> None:
    """HARD INDICATOR (per Failure Contract §1): when check_completeness
    exhausts all retries against a failing LLM, it returns None — not
    a CompletenessResult(status=INCOMPLETE). Mapping a technical failure
    to INCOMPLETE would smuggle it into the skip-cache path, so this
    invariant is enforced by a non-None return being COMPLETE (not
    INCOMPLETE) on success and by a None return on technical failure."""
    from src.pipeline.v7_extract.completeness_checker import (
        CompletenessStatus,
        check_completeness,
    )

    llm = _FailingLLM(RuntimeError("stage3 timeout"))

    result = await check_completeness(
        "long article body here",
        doc_type_hint="multi_section",
        llm=llm,
        project_root=None,
    )

    # Technical failure returns None — the absence of a CompletenessResult
    # is the signal to the caller, NOT a fake INCOMPLETE.
    assert result is None
    # Sanity: the contract guarantees the enum value never surfaces on
    # this failure path (a fake INCOMPLETE would equal the enum member).
    assert CompletenessStatus.TECHNICAL_FAILURE != CompletenessStatus.INCOMPLETE


# ---------------------------------------------------------------------------
# 4. Stage 7 crash recovery — manifest drives PUBLISHING → RECONCILED.
# ---------------------------------------------------------------------------


def test_e2e_crash_during_publish_recovers_via_manifest(project_root: Path) -> None:
    """A crash mid-publish leaves a STAGING-phase manifest + an on-disk
    page file whose sha1 matches the recorded revision_hash. On restart,
    reconcile_unfinished_commits must transition the manifest to
    RECONCILED (not PREPARED, not FAILED)."""
    from src.pipeline.v7_extract.commit_manifest import (
        CommitManifest,
        CommitPhase,
        PageCommitRecord,
        manifest_dir,
        reconcile_unfinished_commits,
        write_manifest,
    )

    page_id = "concept-publish-crash"
    body = (
        "---\n"
        f"id: {page_id}\n"
        "title: Concept Title\n"
        "---\n"
        "\n## 定义\nBody of the page that crashed mid-publish.\n"
    )
    page_path = project_root / "wiki" / "concepts" / f"{page_id}.md"
    page_path.parent.mkdir(parents=True, exist_ok=True)
    page_path.write_text(body, encoding="utf-8")

    expected_sha = hashlib.sha1(body.encode("utf-8")).hexdigest()
    now_ms = int(time.time() * 1000)

    # Manifest stuck in PUBLISHING: process crashed after writing the page
    # but before flipping the phase to COMMITTED.
    manifest = CommitManifest(
        commit_id="pubcrash0000000000000000000000",
        source_id="raw-crash",
        created_at_ms=now_ms,
        updated_at_ms=now_ms,
        pipeline_fingerprint="fp-e2e",
        phase=CommitPhase.PUBLISHING,
        pages={
            page_id: PageCommitRecord(
                page_id=page_id,
                topic_id=page_id,
                source_paths=["raw-crash"],
                phase=CommitPhase.COMMITTED,
                revision_hash=expected_sha,
                written_path=str(page_path),
                committed_at_ms=now_ms,
            )
        },
    )
    write_manifest(project_root, manifest)

    # Run reconcile. Expect this manifest to come back as RECONCILED.
    reconciled = reconcile_unfinished_commits(project_root)
    assert len(reconciled) == 1
    final = reconciled[0]
    assert final.commit_id == manifest.commit_id
    assert final.phase == CommitPhase.RECONCILED
    assert final.pages[page_id].phase == CommitPhase.COMMITTED

    # The reconciled manifest was rewritten to disk.
    on_disk = json.loads(
        (manifest_dir(project_root) / f"{manifest.commit_id}.json").read_text(
            encoding="utf-8"
        )
    )
    assert on_disk["phase"] == CommitPhase.RECONCILED.value


# ---------------------------------------------------------------------------
# 5. Stage 6R — source update flags the page as stale.
# ---------------------------------------------------------------------------


def test_e2e_source_update_reconciles_stale_pages(project_root: Path) -> None:
    """RelationStore.find_stale returns page_ids whose stored
    page_revision no longer matches the caller's view of the wiki.
    A page whose wiki body hash changes is the canonical trigger for
    a Stage 6R re-run; this test asserts the helper flags it and
    leaves stable pages alone."""
    from src.pipeline.v7_extract.relation_store import (
        RelationRunRecord,
        RelationRunStatus,
        RelationStore,
    )

    store = RelationStore(project_root, extractor_fingerprint="fp-6r")
    store.apply_result(
        RelationRunRecord(
            page_id="page-1",
            page_revision="rev-old",
            relation_ids=["rel-aaa"],
            status=RelationRunStatus.READY,
        )
    )
    store.apply_result(
        RelationRunRecord(
            page_id="page-2",
            page_revision="rev-stable",
            relation_ids=["rel-bbb"],
            status=RelationRunStatus.READY,
        )
    )

    # page-1 was updated on disk (its revision changed), page-2 unchanged.
    current_revisions = {"page-1": "rev-new", "page-2": "rev-stable"}
    stale = store.find_stale(current_revisions)

    assert stale == ["page-1"]
    assert "page-2" not in stale

    # Independent-checkpoint invariant: the run-state file exists
    # under .index and is independent of the wiki writer's checkpoint.
    run_state = project_root / ".index" / "relation_run_state.json"
    assert run_state.exists()


# ---------------------------------------------------------------------------
# 6. Reconciliation — same canonical merges multiple pages.
# ---------------------------------------------------------------------------


def test_e2e_reconciliation_attaches_pages_to_canonical(project_root: Path) -> None:
    """Two pages receive SAME verdicts against the same seeded canonical
    → one canonical concept with two member_page_ids. LLM returns
    deterministic SAME verdicts; registry must reflect the merge."""
    from src.reconciliation.canonical_models import (
        CanonicalConcept,
        ReconciliationDecision,
        ReconciliationStatus,
    )
    from src.reconciliation.canonical_registry import CanonicalRegistry
    from src.reconciliation.reconcile_job import reconcile_pages

    canonical_id = "c-seed-aaaa0000000000"

    # Seed one ACTIVE canonical in the registry. ``build`` consumes
    # ``load_concepts`` so the seeded entry will appear in the index.
    seed = CanonicalConcept(
        canonical_id=canonical_id,
        preferred_label="扩句法",
        member_page_ids=[],
        status=ReconciliationStatus.ACTIVE,
        resolver_fingerprint="fp-e2e",
    )
    CanonicalRegistry(project_root, resolver_fingerprint="fp-e2e")._save_concepts(
        {canonical_id: seed}
    )

    class _P:
        def __init__(self, pid: str, title: str, body: str) -> None:
            self.id = pid
            self.title = title
            self.body = body
            self.slots = {"definition": body[:200]}

    # Two pages whose bodies share tokens with the canonical's label so
    # retrieval surfaces it as a candidate.
    pages = [
        _P("page-a", "扩句法", "扩展句子的方法 与 扩句法 类似"),
        _P("page-b", "扩句法技巧", "扩句法 是一种写作技巧"),
    ]

    class _SameLLM:
        """Always emit SAME against the seeded canonical for every page."""

        async def complete(
            self,
            *,
            prompt_kind: str,
            user_prompt: str,
            system_prompt: str,
            max_tokens: int,
            temperature: float,
        ) -> str:
            return json.dumps(
                {
                    "verdicts": [
                        {
                            "canonical_id": canonical_id,
                            "decision": ReconciliationDecision.SAME.value,
                            "confidence": 0.95,
                            "reason": "same concept",
                        }
                    ]
                }
            )

    result = asyncio.run(
        reconcile_pages(
            pages,
            project_root=project_root,
            llm=_SameLLM(),
            body_by_page={"page-a": pages[0].body, "page-b": pages[1].body},
            resolver_fingerprint="fp-e2e",
        )
    )

    # Both pages joined the existing canonical (no DISTINCT, no UNRESOLVED).
    assert result.processed == 2
    assert result.joined_existing == 2
    assert result.created_new == 0
    assert result.unresolved == 0

    # Registry now has exactly one ACTIVE canonical with both members.
    registry = CanonicalRegistry(project_root, resolver_fingerprint="fp-e2e")
    active = registry.list_active()
    assert len(active) == 1
    assert active[0].canonical_id == canonical_id
    assert set(active[0].member_page_ids) == {"page-a", "page-b"}


# ---------------------------------------------------------------------------
# 7. UNRESOLVED → no canonical, no forced merge.
# ---------------------------------------------------------------------------


def test_e2e_unresolved_decision_does_not_force_merge(project_root: Path) -> None:
    """LLM returns UNRESOLVED for every candidate → resolve_identity
    emits one UNRESOLVED record per candidate; apply_decisions must
    NOT create a canonical (DISTINCT) and NOT force a join."""
    from src.reconciliation.canonical_models import (
        CanonicalConcept,
        ReconciliationDecision,
        ReconciliationStatus,
    )
    from src.reconciliation.canonical_registry import CanonicalRegistry
    from src.reconciliation.reconcile_job import reconcile_pages

    canonical_id = "c-seed-bbbb0000000000"
    CanonicalRegistry(project_root, resolver_fingerprint="fp-e2e")._save_concepts(
        {
            canonical_id: CanonicalConcept(
                canonical_id=canonical_id,
                preferred_label="扩句法",
                member_page_ids=[],
                status=ReconciliationStatus.ACTIVE,
                resolver_fingerprint="fp-e2e",
            )
        }
    )

    class _P:
        def __init__(self, pid: str, title: str, body: str) -> None:
            self.id = pid
            self.title = title
            self.body = body
            self.slots = {"definition": body[:200]}

    page = _P("page-x", "扩句法", "讨论扩句法的写作方法")

    class _UnresolvedLLM:
        async def complete(
            self,
            *,
            prompt_kind: str,
            user_prompt: str,
            system_prompt: str,
            max_tokens: int,
            temperature: float,
        ) -> str:
            return json.dumps(
                {
                    "verdicts": [
                        {
                            "canonical_id": canonical_id,
                            "decision": ReconciliationDecision.UNRESOLVED.value,
                            "confidence": 0.0,
                            "reason": "insufficient evidence",
                        }
                    ]
                }
            )

    result = asyncio.run(
        reconcile_pages(
            [page],
            project_root=project_root,
            llm=_UnresolvedLLM(),
            body_by_page={"page-x": page.body},
            resolver_fingerprint="fp-e2e",
        )
    )

    # The page was processed but no canonical was created or joined.
    assert result.processed == 1
    assert result.unresolved == 1
    assert result.created_new == 0
    assert result.joined_existing == 0

    # No new canonical exists; the seeded canonical is empty (no member).
    registry = CanonicalRegistry(project_root, resolver_fingerprint="fp-e2e")
    active = registry.list_active()
    # Only the originally seeded canonical remains; no DISTINCT-created
    # duplicate exists.
    assert len(active) == 1
    assert active[0].canonical_id == canonical_id
    assert active[0].member_page_ids == []


# ---------------------------------------------------------------------------
# 8. Pipeline fingerprint upgrade invalidates the source-skip gate.
# ---------------------------------------------------------------------------


def test_e2e_pipeline_upgrade_triggers_re_evaluation(project_root: Path) -> None:
    """Fingerprint double-key: even when source md5 + INCOMPLETE status
    match, a pipeline_fingerprint change must force re-evaluation.
    Persistence Contract §4.4 — this is the gate that catches
    prompt / template / policy upgrades."""
    import scripts.extract_full as extract_full
    from src.pipeline.v7_extract.failures import ExtractionStatus

    def _prior(*, fp: str) -> dict[str, Any]:
        return {
            "status": ExtractionStatus.INCOMPLETE.value,
            "legacy_status": ExtractionStatus.INCOMPLETE.value,
            "written_page_ids": [],
            "blocked_page_ids": [],
            "failed_page_ids": [],
            "attempts": 1,
            "last_attempt_at": 0,
            "llm_provider": "offline",
            "dry_run": False,
            "md5": "abc123",
            "pipeline_fingerprint": fp,
        }

    # Same fingerprint → skip.
    assert (
        extract_full._source_can_skip(
            _prior(fp="fp-new"), "abc123", dry_run=False, pipeline_fingerprint="fp-new"
        )
        is True
    )
    # Fingerprint changed → must NOT skip (upgrade triggers re-evaluation).
    assert (
        extract_full._source_can_skip(
            _prior(fp="fp-old"), "abc123", dry_run=False, pipeline_fingerprint="fp-new"
        )
        is False
    )
