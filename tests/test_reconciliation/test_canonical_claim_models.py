"""Task 34 — CanonicalClaim model + ClaimReconciliationDecision enum.

Three RED probes (each a contract assertion):

  * test_canonical_claim_id_is_deterministic_hash
        — Identity Contract: canonical_claim_id = "cc-<sha1[:12]>",
          deterministic from (canonical_id, text_hash, support_kind).
          The LLM never produces this id; it is script-owned.

  * test_claim_decision_enum_has_five_values
        — ClaimReconciliationDecision has exactly 5 members:
          same / overlap / conflict / unresolved / single. A subset
          of the 8-way ReconciliationDecision used by Phase 1.

  * test_canonical_claim_member_ids_are_deduped
        — add_member_claim is idempotent: calling twice with the same
          claim_id does not duplicate, mirroring Phase 1's
          CanonicalConcept.add_member discipline.

Contract summary (see canonical_claim_models.py docstring):
  canonical_claim_id = "cc-" + sha1(f"{cid}|{text_hash}|{support_kind}")[:12]
  text_hash         = sha1(text.encode("utf-8"))[:8]
  Identity Contract: LLM never emits canonical_claim_id.
  Failure Contract: helper functions never raise (sha1 is total).
"""
from __future__ import annotations


def test_canonical_claim_id_is_deterministic_hash():
    """canonical_claim_id 是 cc-<sha1(canonical_id|text_hash|support_kind)[:12]>。

    Same inputs → same id; different text/support_kind → different id.
    Script-owned (LLM 永不输出)。
    """
    from src.reconciliation.canonical_claim_models import canonical_claim_id_for

    cid = "c-1234567890abcdef"

    # Same inputs → same id
    id_a = canonical_claim_id_for(cid, "扩句法是一种句式", "explicit")
    id_b = canonical_claim_id_for(cid, "扩句法是一种句式", "explicit")
    assert id_a == id_b
    assert id_a.startswith("cc-")
    # sha1[:12] = 12 hex chars; total len = 3 ("cc-") + 12 = 15
    assert len(id_a) == 3 + 12

    # Different text → different id
    id_c = canonical_claim_id_for(cid, "不同的文本", "explicit")
    assert id_c != id_a

    # Different support_kind → different id
    id_d = canonical_claim_id_for(cid, "扩句法是一种句式", "inferred")
    assert id_d != id_a


def test_claim_decision_enum_has_five_values():
    """ClaimReconciliationDecision 5 个值 (Phase 1 8 态的子集)"""
    from src.reconciliation.canonical_claim_models import (
        ClaimReconciliationDecision,
    )

    expected = {"same", "overlap", "conflict", "unresolved", "single"}
    actual = {d.value for d in ClaimReconciliationDecision}
    assert actual == expected
    assert len(ClaimReconciliationDecision) == 5
    # Each value parses back via the enum constructor
    for v in expected:
        assert ClaimReconciliationDecision(v).value == v


def test_canonical_claim_member_ids_are_deduped():
    """add_member_claim 幂等：同名 claim_id 加两次不重复。

    Mirrors Phase 1's CanonicalConcept.add_member discipline:
    idempotent insertion into member_claim_ids.
    """
    from src.reconciliation.canonical_claim_models import (
        CanonicalClaim,
        ClaimReconciliationDecision,
        RelationSupportKind,
    )

    cc = CanonicalClaim(
        canonical_claim_id="cc-abcdef123456",
        canonical_id="c-cafebabe12345678",
        text="扩句法通过增加修饰成分扩展句子",
        member_claim_ids=[],
        decision=ClaimReconciliationDecision.SAME,
        confidence=0.9,
        support_kind=RelationSupportKind.EXPLICIT,
        created_at_ms=1000,
        updated_at_ms=1000,
    )
    # Add same claim_id twice
    cc.add_member_claim("claim-001")
    cc.add_member_claim("claim-001")
    assert cc.member_claim_ids == ["claim-001"]

    # Add different claim_id
    cc.add_member_claim("claim-002")
    cc.add_member_claim("claim-003")
    assert cc.member_claim_ids == ["claim-001", "claim-002", "claim-003"]

    # Re-add an existing one → still no duplicates
    cc.add_member_claim("claim-001")
    assert cc.member_claim_ids == ["claim-001", "claim-002", "claim-003"]
