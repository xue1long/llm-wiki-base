"""Task 34 — CanonicalClaimRegistry: persistent canonical-claim store.

Four RED probes (each a contract assertion):

  * test_registry_persists_canonical_claims
        — save + load round-trip: CanonicalClaim survives JSON
          serialization (canonical_claims.json under
          <root>/.index/reconciliation/).

  * test_apply_decisions_groups_same_claims_into_one_canonical_claim
        — 3 member claims all SAME → 1 CanonicalClaim with 3 members
          (Phase 1 join-existing semantics, applied at claim level).

  * test_apply_decisions_separates_conflicting_claims
        — 2 member claims CONFLICT → 2 CanonicalClaims, each with 1
          member (split on conflict; matches spec §5.2).

  * test_registry_reversible_per_claim
        — remove_member_claim reverses a single member without
          deleting the canonical_claim (empty members preserved;
          re-add recovers membership).

Contract summary (see canonical_claim_registry.py docstring):
  Storage:
    <root>/.index/reconciliation/canonical_claims.json
    <root>/.index/reconciliation/claim_decision_log.jsonl (append-only)

  Apply rules (priority):
    same > overlap > conflict > unresolved > single

  Reversibility:
    remove_member_claim drops the member but preserves the
    CanonicalClaim; re-adding restores membership (idempotent).
"""
from __future__ import annotations


def test_registry_persists_canonical_claims(tmp_path):
    """save + load round-trip：CanonicalClaim survives persist"""
    from src.reconciliation.canonical_claim_models import (
        CanonicalClaim,
        ClaimReconciliationDecision,
        RelationSupportKind,
        canonical_claim_id_for,
    )
    from src.reconciliation.canonical_claim_registry import (
        CanonicalClaimRegistry,
    )

    reg = CanonicalClaimRegistry(tmp_path, resolver_fingerprint="fp-1")
    cid = "c-aaaa111122223333"
    text = "扩句法通过增加修饰成分扩展句子"
    cc = CanonicalClaim(
        canonical_claim_id=canonical_claim_id_for(cid, text, "explicit"),
        canonical_id=cid,
        text=text,
        member_claim_ids=["claim-A", "claim-B"],
        decision=ClaimReconciliationDecision.SAME,
        confidence=0.9,
        support_kind=RelationSupportKind.EXPLICIT,
        created_at_ms=1000,
        updated_at_ms=2000,
        resolver_fingerprint="fp-1",
    )

    loaded = reg.load_canonical_claims()
    loaded[cc.canonical_claim_id] = cc
    reg.save_canonical_claims(loaded)

    # New registry instance — proves round-trip via disk
    reg2 = CanonicalClaimRegistry(tmp_path)
    reloaded = reg2.load_canonical_claims()
    assert cc.canonical_claim_id in reloaded
    rc = reloaded[cc.canonical_claim_id]
    assert rc.canonical_id == cid
    assert rc.text == text
    assert rc.member_claim_ids == ["claim-A", "claim-B"]
    assert rc.decision == ClaimReconciliationDecision.SAME
    assert rc.confidence == 0.9
    assert rc.support_kind == RelationSupportKind.EXPLICIT
    assert rc.resolver_fingerprint == "fp-1"


def test_apply_decisions_groups_same_claims_into_one_canonical_claim(tmp_path):
    """3 个 member claims 全部 SAME → 1 个 CanonicalClaim 含 3 members

    Phase 1's "join existing" semantics adapted to claim level:
    LLM emits "same" between (A,B), (B,C), (A,C) → one canonical
    claim grouping all three members.
    """
    from src.reconciliation.canonical_claim_models import (
        ClaimDecisionRecord,
        ClaimReconciliationDecision,
    )
    from src.reconciliation.canonical_claim_registry import (
        CanonicalClaimRegistry,
    )

    reg = CanonicalClaimRegistry(tmp_path, resolver_fingerprint="fp-1")
    cid = "c-bbbb111122223333"

    decisions = [
        ClaimDecisionRecord(
            decision_id="dec-c1",
            pair_id="claim-A|claim-B",
            canonical_id=cid,
            decision=ClaimReconciliationDecision.SAME,
            confidence=0.9,
            reason="same",
            evidence_refs=[],
            resolver_fingerprint="fp-1",
            created_at_ms=1000,
        ),
        ClaimDecisionRecord(
            decision_id="dec-c2",
            pair_id="claim-B|claim-C",
            canonical_id=cid,
            decision=ClaimReconciliationDecision.SAME,
            confidence=0.85,
            reason="same",
            evidence_refs=[],
            resolver_fingerprint="fp-1",
            created_at_ms=1000,
        ),
    ]

    canonical_claims = reg.apply_claim_decisions(
        cid, decisions, resolver_fingerprint="fp-1"
    )

    # All SAME → 1 CanonicalClaim containing all 3 member claims
    assert len(canonical_claims) == 1
    cc = canonical_claims[0]
    assert cc.canonical_id == cid
    assert sorted(cc.member_claim_ids) == ["claim-A", "claim-B", "claim-C"]
    assert cc.decision == ClaimReconciliationDecision.SAME


def test_apply_decisions_separates_conflicting_claims(tmp_path):
    """2 个 claims CONFLICT → 2 个 CanonicalClaim 各自 1 member

    Spec §5.2: CONFLICT splits — each conflicting claim gets its own
    CanonicalClaim (no shared membership).
    """
    from src.reconciliation.canonical_claim_models import (
        ClaimDecisionRecord,
        ClaimReconciliationDecision,
    )
    from src.reconciliation.canonical_claim_registry import (
        CanonicalClaimRegistry,
    )

    reg = CanonicalClaimRegistry(tmp_path, resolver_fingerprint="fp-1")
    cid = "c-cccc111122223333"

    decisions = [
        ClaimDecisionRecord(
            decision_id="dec-d1",
            pair_id="claim-X|claim-Y",
            canonical_id=cid,
            decision=ClaimReconciliationDecision.CONFLICT,
            confidence=0.95,
            reason="contradict",
            evidence_refs=[],
            resolver_fingerprint="fp-1",
            created_at_ms=1000,
        ),
    ]

    canonical_claims = reg.apply_claim_decisions(
        cid, decisions, resolver_fingerprint="fp-1"
    )

    # CONFLICT → 2 separate CanonicalClaims, each with 1 member
    assert len(canonical_claims) == 2
    members_sets = sorted([sorted(cc.member_claim_ids) for cc in canonical_claims])
    assert members_sets == [["claim-X"], ["claim-Y"]]
    for cc in canonical_claims:
        assert cc.decision == ClaimReconciliationDecision.CONFLICT
        assert cc.canonical_id == cid


def test_registry_reversible_per_claim(tmp_path):
    """remove_member_claim 撤销 + re-add 恢复（empty members 保留）

    Spec §5.2 / Reversibility: removing the last member does NOT
    delete the CanonicalClaim; it preserves an empty-members record
    so a future re-add (or reconciliation pass) can repopulate it.
    """
    from src.reconciliation.canonical_claim_models import (
        CanonicalClaim,
        ClaimReconciliationDecision,
        RelationSupportKind,
        canonical_claim_id_for,
    )
    from src.reconciliation.canonical_claim_registry import (
        CanonicalClaimRegistry,
    )

    reg = CanonicalClaimRegistry(tmp_path, resolver_fingerprint="fp-1")
    cid = "c-dddd111122223333"
    text = "test reversible claim"

    # Setup a CanonicalClaim with 2 members via direct write
    cc = CanonicalClaim(
        canonical_claim_id=canonical_claim_id_for(cid, text, "explicit"),
        canonical_id=cid,
        text=text,
        member_claim_ids=["m1", "m2"],
        decision=ClaimReconciliationDecision.SAME,
        confidence=0.9,
        support_kind=RelationSupportKind.EXPLICIT,
        created_at_ms=1000,
        updated_at_ms=1000,
        resolver_fingerprint="fp-1",
    )
    reg.save_canonical_claims({cc.canonical_claim_id: cc})

    # Remove m1
    assert reg.remove_member_claim(cc.canonical_claim_id, "m1") is True
    after = reg.load_canonical_claims()[cc.canonical_claim_id]
    assert "m1" not in after.member_claim_ids
    assert "m2" in after.member_claim_ids
    # CanonicalClaim still exists (not deleted)
    assert cc.canonical_claim_id in reg.load_canonical_claims()

    # Remove last member
    assert reg.remove_member_claim(cc.canonical_claim_id, "m2") is True
    after = reg.load_canonical_claims()[cc.canonical_claim_id]
    assert after.member_claim_ids == []
    # Empty record preserved (not deleted)
    assert cc.canonical_claim_id in reg.load_canonical_claims()

    # Re-add m1 — should restore. Persist via save_canonical_claims
    # after mutating the loaded record (re-loading the file does not
    # yield an in-memory reference; we hold the loaded dict and write
    # it back).
    store = reg.load_canonical_claims()
    store[cc.canonical_claim_id].add_member_claim("m1")
    reg.save_canonical_claims(store)
    final = reg.load_canonical_claims()[cc.canonical_claim_id]
    assert "m1" in final.member_claim_ids
