"""Task 30 — CanonicalRegistry: persistent canonical concept store + F4/F15.

Eight RED probes (each a contract assertion):

  * test_apply_decisions_creates_canonical_for_distinct
        — DISTINCT decision → new canonical with the page as first member.

  * test_apply_decisions_joins_existing_for_same
        — SAME decision → joins the existing canonical's membership
          (resolver_fingerprint bumped per F4).

  * test_remove_membership_is_reversible
        — remove_membership is reversible: re-applying SAME re-adds.

  * test_tombstone_when_last_member_removed
        — last member out → status = TOMBSTONED; aliases preserved.

  * test_atomic_write_survives_crash
        — stray .tmp file on disk is ignored on next load (atomic
          write semantics — tmp+rename pattern).

  * test_resolver_fingerprint_drift_marks_stale
        — F4 hard requirement: ACTIVE concepts whose
          resolver_fingerprint no longer matches the current one are
          transitioned to STALE.

  * test_stale_canonical_can_be_re_evaluated_incremental
        — STALE canonicals can be revived through apply_decisions
          (incremental re-evaluation).

  * test_alias_single_source_of_truth
        — F15 hard requirement: alias writes go through
          CanonicalRegistry.add_alias → SlugAliasRegistry adapter; the
          same alias text cannot be redirected to a different
          canonical (keep-first semantics).

Contract summary (see canonical_registry.py docstring):

  Storage:
    <root>/.index/reconciliation/canonical_concepts.json
    <root>/.index/reconciliation/alias_records.json
    <root>/.index/reconciliation/decision_log.jsonl (append-only audit)

  Apply rules (priority):
    same > alias > conflict > overlap > broader > narrower >
    distinct > unresolved

  Reversibility:
    remove_membership drops the member but preserves the canonical and
    its aliases; re-applying SAME re-adds.
"""
from __future__ import annotations


def test_apply_decisions_creates_canonical_for_distinct(tmp_path):
    """DISTINCT decision → 新建 canonical"""
    from src.reconciliation.canonical_registry import CanonicalRegistry
    from src.reconciliation.canonical_models import (
        ReconciliationDecision,
        ReconciliationDecisionRecord,
    )

    reg = CanonicalRegistry(tmp_path, resolver_fingerprint="fp-1")
    decisions = [
        ReconciliationDecisionRecord(
            decision_id="dec-1",
            candidate_page_id="page-x",
            candidate_canonical_id=None,
            decision=ReconciliationDecision.DISTINCT,
            confidence=0.9,
            reason="new concept",
            evidence_refs=[],
            resolver_fingerprint="fp-1",
            created_at_ms=1000,
        )
    ]
    touched = reg.apply_decisions(
        "page-x", decisions, language="zh", resolver_fingerprint="fp-1"
    )
    assert len(touched) == 1
    assert touched[0].member_page_ids == ["page-x"]
    assert touched[0].resolver_fingerprint == "fp-1"


def test_apply_decisions_joins_existing_for_same(tmp_path):
    """SAME decision → 加入已有 canonical 的 membership"""
    from src.reconciliation.canonical_registry import CanonicalRegistry
    from src.reconciliation.canonical_models import (
        CanonicalConcept,
        ReconciliationDecision,
        ReconciliationDecisionRecord,
    )

    reg = CanonicalRegistry(tmp_path, resolver_fingerprint="fp-1")
    # 通过 DISTINCT 先建一个
    reg.apply_decisions(
        "page-y",
        [
            ReconciliationDecisionRecord(
                decision_id="dec-pre",
                candidate_page_id="page-y",
                candidate_canonical_id=None,
                decision=ReconciliationDecision.DISTINCT,
                confidence=0.9,
                reason="setup",
                evidence_refs=[],
                resolver_fingerprint="fp-1",
                created_at_ms=0,
            )
        ],
        resolver_fingerprint="fp-1",
    )
    existing_cid = reg.list_active()[0].canonical_id

    # SAME decision
    decisions = [
        ReconciliationDecisionRecord(
            decision_id="dec-2",
            candidate_page_id="page-x",
            candidate_canonical_id=existing_cid,
            decision=ReconciliationDecision.SAME,
            confidence=0.85,
            reason="same concept",
            evidence_refs=[],
            resolver_fingerprint="fp-1",
            created_at_ms=1000,
        )
    ]
    touched = reg.apply_decisions(
        "page-x", decisions, resolver_fingerprint="fp-1"
    )
    assert len(touched) == 1
    cc = reg.get_concept(existing_cid)
    assert cc is not None
    assert "page-x" in cc.member_page_ids
    assert cc.resolver_fingerprint == "fp-1"  # F4 更新


def test_remove_membership_is_reversible(tmp_path):
    """remove_membership 可重新加入（reversible）"""
    from src.reconciliation.canonical_registry import CanonicalRegistry
    from src.reconciliation.canonical_models import (
        ReconciliationDecision,
        ReconciliationDecisionRecord,
    )

    reg = CanonicalRegistry(tmp_path)
    reg.apply_decisions(
        "page-x",
        [
            ReconciliationDecisionRecord(
                decision_id="dec-1",
                candidate_page_id="page-x",
                candidate_canonical_id=None,
                decision=ReconciliationDecision.DISTINCT,
                confidence=0.9,
                reason="new",
                evidence_refs=[],
                resolver_fingerprint="fp",
                created_at_ms=0,
            )
        ],
        resolver_fingerprint="fp",
    )
    cid = reg.list_active()[0].canonical_id

    assert reg.remove_membership("page-x", cid) is True
    cc = reg.get_concept(cid)
    assert cc is not None
    assert "page-x" not in cc.member_page_ids

    # re-apply SAME
    reg.apply_decisions(
        "page-x",
        [
            ReconciliationDecisionRecord(
                decision_id="dec-2",
                candidate_page_id="page-x",
                candidate_canonical_id=cid,
                decision=ReconciliationDecision.SAME,
                confidence=0.9,
                reason="rejoin",
                evidence_refs=[],
                resolver_fingerprint="fp",
                created_at_ms=1000,
            )
        ],
        resolver_fingerprint="fp",
    )
    cc = reg.get_concept(cid)
    assert cc is not None
    assert "page-x" in cc.member_page_ids


def test_tombstone_when_last_member_removed(tmp_path):
    """最后一个 member 被移除 → canonical TOMBSTONED（aliases 保留）"""
    from src.reconciliation.canonical_registry import CanonicalRegistry
    from src.reconciliation.canonical_models import (
        CanonicalConcept,
        ReconciliationDecision,
        ReconciliationStatus,
    )

    reg = CanonicalRegistry(tmp_path)
    reg.add_alias(
        "foo",
        "c-aaaa",
        language="en",
        provenance="resolver",
        resolver_fingerprint="fp",
    )
    # 直接 setup canonical
    cc = CanonicalConcept(
        canonical_id="c-aaaa",
        preferred_label="X",
        member_page_ids=["page-x"],
        resolver_fingerprint="fp",
    )
    # 通过 _save_concepts 直接设
    reg._save_concepts({cc.canonical_id: cc})

    # remove last member
    reg.remove_membership("page-x", cc.canonical_id)

    after = reg.get_concept(cc.canonical_id)
    assert after is not None
    assert after.status == ReconciliationStatus.TOMBSTONED
    # aliases 保留
    assert reg.get_by_alias("foo", "en") is not None


def test_atomic_write_survives_crash(tmp_path):
    """tmp+rename 模式，写过程中崩 → 旧文件完整"""
    from src.reconciliation.canonical_registry import CanonicalRegistry
    from src.reconciliation.canonical_models import ReconciliationDecision, ReconciliationDecisionRecord
    from src.reconciliation.canonical_registry import canonical_concepts_path

    reg = CanonicalRegistry(tmp_path)
    reg.apply_decisions(
        "page-1",
        [
            ReconciliationDecisionRecord(
                decision_id="d1",
                candidate_page_id="page-1",
                candidate_canonical_id=None,
                decision=ReconciliationDecision.DISTINCT,
                confidence=0.9,
                reason="x",
                evidence_refs=[],
                resolver_fingerprint="fp",
                created_at_ms=0,
            )
        ],
        resolver_fingerprint="fp",
    )
    # 模拟 crash 期间存在 .tmp 文件：直接创建 .tmp
    tmp_file = canonical_concepts_path(tmp_path).with_suffix(".json.tmp")
    tmp_file.write_text("garbage", encoding="utf-8")
    # 下次 load 应该忽略 .tmp
    reg2 = CanonicalRegistry(tmp_path)
    concepts = reg2.load_concepts()
    assert len(concepts) == 1


def test_resolver_fingerprint_drift_marks_stale(tmp_path):
    """F4 硬指标：resolver_fingerprint 升级 → 旧 canonical STALE"""
    from src.reconciliation.canonical_registry import CanonicalRegistry
    from src.reconciliation.canonical_models import (
        CanonicalConcept,
        ReconciliationStatus,
    )

    reg = CanonicalRegistry(tmp_path, resolver_fingerprint="fp-old")
    # 直接 setup 一个 ACTIVE canonical
    cc = CanonicalConcept(
        canonical_id="c-aaaa",
        preferred_label="X",
        member_page_ids=["page-1"],
        status=ReconciliationStatus.ACTIVE,
        resolver_fingerprint="fp-old",
    )
    reg._save_concepts({cc.canonical_id: cc})

    # 模拟 fingerprint 升级
    newly_stale = reg.mark_stale_concepts("fp-new")
    assert "c-aaaa" in newly_stale
    after = reg.get_concept("c-aaaa")
    assert after is not None
    assert after.status == ReconciliationStatus.STALE


def test_stale_canonical_can_be_re_evaluated_incremental(tmp_path):
    """STALE canonical 可通过 apply_decisions 重激活（incremental re-evaluation）"""
    from src.reconciliation.canonical_registry import CanonicalRegistry
    from src.reconciliation.canonical_models import (
        CanonicalConcept,
        ReconciliationDecision,
        ReconciliationDecisionRecord,
        ReconciliationStatus,
    )

    reg = CanonicalRegistry(tmp_path)
    # 直接 setup 一个 ACTIVE canonical with fp-old
    cc = CanonicalConcept(
        canonical_id="c-aaaa",
        preferred_label="X",
        member_page_ids=["page-1"],
        status=ReconciliationStatus.ACTIVE,
        resolver_fingerprint="fp-old",
    )
    reg._save_concepts({cc.canonical_id: cc})
    # 让它 STALE
    reg.mark_stale_concepts("fp-new")
    assert reg.get_concept("c-aaaa").status == ReconciliationStatus.STALE

    # SAME with new fingerprint → 重激活
    reg.apply_decisions(
        "page-new",
        [
            ReconciliationDecisionRecord(
                decision_id="d-rev",
                candidate_page_id="page-new",
                candidate_canonical_id="c-aaaa",
                decision=ReconciliationDecision.SAME,
                confidence=0.9,
                reason="re-eval",
                evidence_refs=[],
                resolver_fingerprint="fp-new",
                created_at_ms=0,
            )
        ],
        resolver_fingerprint="fp-new",
    )
    after = reg.get_concept("c-aaaa")
    assert after is not None
    assert after.status == ReconciliationStatus.ACTIVE
    assert "page-new" in after.member_page_ids
    assert after.resolver_fingerprint == "fp-new"


def test_alias_single_source_of_truth(tmp_path):
    """F15 硬指标：alias 唯一写入路径是 CanonicalRegistry.add_alias"""
    from src.reconciliation.canonical_registry import CanonicalRegistry
    from src.reconciliation.canonical_models import (
        CanonicalConcept,
        ReconciliationStatus,
    )

    # 模拟 SlugAliasRegistry
    class MockSlugRegistry:
        def __init__(self):
            self.aliases = {}

        def register(self, alias_text, canonical_id, **kwargs):
            # Adapter (Task 27) forwards (alias_text, canonical_id); the
            # mock accepts the optional language kwarg for completeness
            # but the test asserts the contract that the canonical_id
            # *value* is what flows through, not the language tag.
            language = kwargs.get("language", "")
            self.aliases[(alias_text, language)] = canonical_id

    mock = MockSlugRegistry()
    reg = CanonicalRegistry(tmp_path, slug_registry=mock)

    # Seed a canonical concept for c-aaaa so get_by_alias can resolve it.
    reg._save_concepts(
        {
            "c-aaaa": CanonicalConcept(
                canonical_id="c-aaaa",
                preferred_label="X",
                member_page_ids=[],
                status=ReconciliationStatus.ACTIVE,
            )
        }
    )

    reg.add_alias(
        "foo",
        "c-aaaa",
        language="en",
        provenance="manual",
        resolver_fingerprint="fp",
    )

    # SlugAliasRegistry 也收到了：canonical_id 是 c-aaaa
    foo_keys = [k for k in mock.aliases if k[0] == "foo"]
    assert len(foo_keys) >= 1
    canonical_ids_for_foo = {mock.aliases[k] for k in foo_keys}
    assert canonical_ids_for_foo == {"c-aaaa"}

    # 二次注册不同 canonical_id → 保留第一个（F15 acceptance）
    reg.add_alias(
        "foo",
        "c-bbbb",
        language="en",
        provenance="manual",
        resolver_fingerprint="fp",
    )
    foo_keys = [k for k in mock.aliases if k[0] == "foo"]
    canonical_ids_for_foo = {mock.aliases[k] for k in foo_keys}
    assert canonical_ids_for_foo == {"c-aaaa"}  # 不变

    # 查询走 alias_records（多语言）
    cc = reg.get_by_alias("foo", "en")
    assert cc is not None
    assert cc.canonical_id == "c-aaaa"
