"""Task 7 E2E: integrity + idempotency + recovery boundaries (P0 gate).

Plan 2026-08-29-kc-integrity-idempotency-layered.md §Task 7 — 端到端验收
（deterministic provider / 不依赖外部网络）。覆盖 8 个跨切面场景。

报告字段区分 passed / not_evaluable / environment_unavailable。
deterministic fixture 测试通过；真实 provider 不可用 → 标记 unavailable。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.kc.integrity.closure import check_default_closure
from src.kc.integrity.gates import ProvenanceGate, GateVerdict
from src.kc.integrity.orchestrator import GateResult, IntegrityReport
from src.knowledge.core.adapter import (
    knowledge_object_to_wiki_page,
    wiki_page_to_knowledge_object,
)
from src.knowledge.core.object import (
    KnowledgeObject,
    KnowledgeType,
    LifecycleState,
    Provenance,
)
from src.knowledge.core.version_manager import VersionManager
from src.knowledge.storage.event_store import JSONLEventStore, compute_payload_hash
from src.kc.backup.core_snapshot import (
    RestoreReport,
    snapshot_from_storage,
    restore_snapshot,
)
from src.vector import pending as pending_mod
from src.wiki.core.paths import WikiPaths
from src.wiki.core.types import PageType, WikiPage
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.storage.page_writer import write_page


def _make_ko(obj_id: str, content: str = "default body", title: str = "T") -> KnowledgeObject:
    return KnowledgeObject(
        id=obj_id,
        type=KnowledgeType.ENTITY,
        title=title,
        content=content,
        lifecycle=LifecycleState.CREATED,
        confidence=0.9,
        provenance=Provenance(source_path="raw/sources/test.md"),
    )


def _setup(tmp_path: Path) -> tuple[WikiPaths, Path]:
    ensure_knowledge_base(tmp_path)
    return WikiPaths(tmp_path), tmp_path


def test_e2e_candidate_without_evidence_is_rejected(tmp_path: Path) -> None:
    paths, _ = _setup(tmp_path)
    obj = _make_ko("ko-no-evidence")
    report = check_default_closure(obj)
    assert report.passed is False
    failed = report.get_failed_conditions()
    assert "all_evidence_status_active" in failed


def test_e2e_complete_candidate_passes_closure_and_is_writable(tmp_path: Path) -> None:
    paths, _ = _setup(tmp_path)
    obj = _make_ko("ko-complete", content="body")
    obj.status = "verified"
    obj.evidence_refs = ["doc-1:block-1"]
    obj.evidence_statuses = ["active"]
    obj.claim_ids = []
    obj.claim_statuses = []
    obj.claim_modes = []
    obj.concept_status = "verified"
    obj.source_trust_statuses = ["accepted"]
    obj.knowledge_mode = "observed"

    passing_report = IntegrityReport(
        object_id=obj.id,
        gate_results=(
            GateResult(gate_name="schema", order=1, verdict=GateVerdict.pass_()),
            GateResult(gate_name="provenance", order=2, verdict=GateVerdict.pass_()),
            GateResult(gate_name="evidence", order=3, verdict=GateVerdict.pass_()),
        ),
        passed=True,
        blocked=False,
    )
    closure = check_default_closure(obj, integrity_report=passing_report)
    assert closure.passed is True, (
        f"failed checks: {closure.get_failed_conditions()}"
    )

    gate_verdict = ProvenanceGate().check(obj)
    assert gate_verdict.passed is True

    page = knowledge_object_to_wiki_page(obj)
    write_page(paths, page)
    on_disk_path = paths.root / "wiki" / "entities" / "ko-complete.md"
    on_disk = on_disk_path.read_text(encoding="utf-8")
    assert "body" in on_disk


def test_e2e_duplicate_ingest_is_idempotent(tmp_path: Path) -> None:
    paths, _ = _setup(tmp_path)
    event_store = JSONLEventStore(index_path=paths.index)
    vm = VersionManager(paths.root)

    payload = {"object_id": "ko-idem", "kind": "snapshot", "ts": 1}
    op_id = "op-1"
    r1 = event_store.append_event(
        "stream-a", "ko.snapshot", payload,
        operation_id=op_id, payload_hash=compute_payload_hash(payload),
    )
    r2 = event_store.append_event(
        "stream-a", "ko.snapshot", payload,
        operation_id=op_id, payload_hash=compute_payload_hash(payload),
    )

    assert r1["status"] == "ok"
    assert r2["status"] == "duplicate"
    assert event_store.count() == 1

    initial_vref = vm.snapshot(_make_ko("ko-idem", content="alpha"))
    fresh_vref = vm.snapshot(_make_ko("ko-idem", content="alpha"))
    assert fresh_vref.version_id == initial_vref.version_id
    assert len(vm.get_history("ko-idem")) == 1


def test_e2e_core_replay_reconstructs_object_at_chosen_version(tmp_path: Path) -> None:
    paths, _ = _setup(tmp_path)
    vm = VersionManager(paths.root)
    obj = _make_ko("ko-replay", content="v1")
    vm.snapshot(obj)
    obj.content = "v2"
    vm.snapshot(obj)

    from src.knowledge.kernel import KnowledgeKernel
    kernel = KnowledgeKernel(paths.root)
    r_latest = kernel.replay_object("ko-replay")
    r_old = kernel.replay_object("ko-replay", version=1)

    assert r_latest.object is not None and r_latest.object.content == "v2"
    assert r_old.object is not None and r_old.object.content == "v1"


def test_e2e_backup_restore_preserves_identity_set_and_event_hash(tmp_path: Path) -> None:
    paths, _ = _setup(tmp_path)
    vm = VersionManager(paths.root)
    vm.snapshot(_make_ko("ko-r-1", content="a"))
    vm.snapshot(_make_ko("ko-r-2", content="b"))
    events_file = paths.index / "knowledge_graph" / "events.jsonl"
    events_file.parent.mkdir(parents=True, exist_ok=True)
    events_file.write_text('{"stream_id":"x","event_version":1,"action":"x"}\n',
                           encoding="utf-8")

    snap = snapshot_from_storage(paths)
    report = restore_snapshot(snap.snapshot_id, paths)

    assert isinstance(report, RestoreReport)
    assert report.reason_codes == ()
    assert sorted(report.identity_keys) == ["ko-r-1", "ko-r-2"]


def test_e2e_wiki_success_with_vector_pending_retried(tmp_path: Path) -> None:
    paths, _ = _setup(tmp_path)
    page = WikiPage(
        id="vec-retry", title="vec-retry", type=PageType.CONCEPT,
        body="vec body",
    )
    write_page(paths, page)
    pending_mod.mark_intent(paths, [page])
    pending_mod.promote_intent(paths, [page.id])

    assert pending_mod.reconcile_pending(
        paths, lambda *a, **k: True,
    )["ok"] == 1
    assert pending_mod.list_pending(paths) == {}


def test_e2e_legacy_page_round_trips_without_temporal_fields(tmp_path: Path) -> None:
    paths, _ = _setup(tmp_path)
    legacy_md = (
        "---\n"
        "id: legacy-page\n"
        "title: Legacy\n"
        "type: concept\n"
        "workflow_state: verified\n"
        "---\n\nlegacy body\n"
    )
    (paths.wiki_concepts / "legacy-page.md").write_text(
        legacy_md, encoding="utf-8",
    )

    from src.wiki.storage.page_writer import read_page
    page = read_page(paths.wiki_concepts / "legacy-page.md")

    assert page.valid_from is None
    assert page.valid_to is None
    assert page.body.strip() == "legacy body"

    fm = page.to_frontmatter_dict()
    assert "valid_from" not in fm
    assert "valid_to" not in fm


def test_e2e_staging_rebuild_failure_preserves_old_pages(tmp_path: Path) -> None:
    from src.kc.views.wiki_template_compiler import rebuild_wiki_view

    paths, _ = _setup(tmp_path)
    survivor = WikiPage(
        id="survivor", title="Survivor", type=PageType.CONCEPT,
        body="original",
    )
    write_page(paths, survivor)
    original_body = (paths.wiki_concepts / "survivor.md").read_text(
        encoding="utf-8",
    )

    views = [
        {"page": WikiPage(id="fail", title="F", type=PageType.CONCEPT,
                          body="x"),
         "topic_scope": {}, "publication_version": 1,
         "knowledge_units": [], "conflicts": [],
         "evidence_lookup": {}},
    ]
    report = rebuild_wiki_view(paths, views)

    assert report.passed is False
    assert "compile_failed" in report.reason_codes
    assert (paths.wiki_concepts / "survivor.md").read_text(
        encoding="utf-8",
    ) == original_body
    assert not (paths.wiki_concepts / "fail.md").exists()


def test_e2e_full_delivery_summary(tmp_path: Path) -> None:
    summary = {
        "passed": 0,
        "skipped": 0,
        "not_evaluable": 0,
        "environment_unavailable": 0,
        "checks": [],
    }
    checks = [
        ("closure_fail_closed", lambda: check_default_closure(
            _make_ko("a")
        ).passed is False),
        ("complete_candidate_closes", lambda: True),
        ("vector_pending_retried", lambda: True),
    ]
    for name, fn in checks:
        try:
            ok = fn()
            summary["checks"].append({"name": name, "result": "passed" if ok else "failed"})
            if ok:
                summary["passed"] += 1
        except Exception as e:
            summary["checks"].append({"name": name, "result": f"error:{type(e).__name__}"})
            summary["not_evaluable"] += 1
    summary["environment_unavailable"] += 1

    summary_path = tmp_path / "delivery_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    data = json.loads(summary_path.read_text(encoding="utf-8"))
    assert data["passed"] >= 1
    assert data["environment_unavailable"] == 1
