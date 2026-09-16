"""Task 34 — Claim resolver: Phase 2 main entry + bounded pair contract.

Three RED probes (each a contract assertion):

  * test_llm_only_returns_decision_not_canonical_claim_id
        — Identity Contract: LLM emits only ``(pair_id, decision,
          confidence, reason)``; the script generates
          ``canonical_claim_id`` from sha1(canonical_id|text_hash|
          support_kind). The LLM never fabricates an id.

  * test_technical_failure_returns_unresolved
        — Failure Contract §1: when the LLM provider raises on every
          retry, every pair returns UNRESOLVED; the function never
          raises.

  * test_bounded_evidence_pack_per_claim_pair
        — Per-pair evidence budget: each claim's evidence excerpt in
          the prompt is bounded; pair_count is exposed for prompt
          truncation logic. Bounded Evidence §3.2 — the LLM never
          sees a full unbounded source.

Contract summary (see claim_resolver.py docstring):
  MAX_CLAIM_PAIRS_PER_RESOLVE_CALL = 50  (R1 audit hard requirement)
  Identity Contract: LLM never emits canonical_claim_id.
  Failure Contract §1: never raises; technical failure → UNRESOLVED.
  pair_id = "{claim_id_a}|{claim_id_b}"  (script-generated; LLM echoes)
"""
from __future__ import annotations


def test_llm_only_returns_decision_not_canonical_claim_id():
    """LLM 输出只有 (pair_id, decision, confidence, reason)；

    canonical_claim_id 完全脚本生成 (sha1 + canonical_id + text_hash
    + support_kind). LLM 不参与 id 生成。

    parse_llm_claim_verdicts must:
      * coerce raw JSON into ClaimDecisionRecord
      * set decision_id from a script-owned source (NOT from LLM)
      * canonical_claim_id on the record itself is empty/None (the
        canonical_claim_id is generated when grouping decisions, not
        on the per-pair record).
    """
    from src.reconciliation.claim_resolver import parse_llm_claim_verdicts
    from src.reconciliation.canonical_claim_models import (
        ClaimReconciliationDecision,
    )

    pairs = [
        ("claim-A", "claim-B"),
    ]

    raw = '{"verdicts": [{"pair_id": "claim-A|claim-B", "decision": "same", "confidence": 0.9, "reason": "agree"}]}'
    decisions = parse_llm_claim_verdicts(
        raw,
        pairs=pairs,
        canonical_id="c-aaaa111122223333",
        resolver_fingerprint="fp-test",
    )

    assert len(decisions) == 1
    d = decisions[0]
    assert d.decision == ClaimReconciliationDecision.SAME
    assert d.pair_id == "claim-A|claim-B"
    assert d.canonical_id == "c-aaaa111122223333"
    assert d.confidence == 0.9
    assert d.resolver_fingerprint == "fp-test"
    # decision_id is script-generated, never provided by LLM. The LLM
    # response did not include any decision_id field; the helper must
    # generate one.
    assert d.decision_id  # non-empty
    assert d.decision_id != ""


def test_technical_failure_returns_unresolved():
    """LLM 全部重试抛异常 → 所有 pair 标 UNRESOLVED (fail-closed)。

    resolve_claim_identity must never raise. When the LLM provider
    raises on every retry, every pair receives an UNRESOLVED verdict
    so the caller can still proceed.
    """
    import asyncio

    from src.reconciliation.canonical_claim_models import (
        ClaimReconciliationDecision,
    )
    from src.reconciliation.claim_resolver import resolve_claim_identity

    class FailingLLM:
        async def complete(
            self,
            *,
            prompt_kind,
            user_prompt,
            system_prompt="",
            max_tokens=4096,
            temperature=0.0,
        ):
            raise RuntimeError("provider timeout")

    # Build minimal Claim objects
    class FakeClaim:
        def __init__(self, claim_id, text):
            self.claim_id = claim_id
            self.text = text
            self.evidence_refs = []

    member_claims = [
        FakeClaim("claim-A", "扩句法增加修饰成分"),
        FakeClaim("claim-B", "扩句法加入形容词"),
        FakeClaim("claim-C", "扩句法不同"),
    ]

    decisions = asyncio.run(
        resolve_claim_identity(
            canonical_id="c-eeee111122223333",
            member_claims=member_claims,
            source_bytes={},
            llm=FailingLLM(),
            resolver_fingerprint="fp-test",
            max_retries=2,
        )
    )

    # Every pair must be UNRESOLVED; function did not raise
    assert len(decisions) >= 1
    for d in decisions:
        assert d.decision == ClaimReconciliationDecision.UNRESOLVED


def test_bounded_evidence_pack_per_claim_pair():
    """evidence pack per claim pair 受 MAX_EVIDENCE_CHARS 限制。

    Per-pair evidence budget enforced: each claim's excerpt is
    truncated to MAX_EVIDENCE_CHARS so the LLM never sees an
    unbounded source body. Pairs are also capped at
    MAX_CLAIM_PAIRS_PER_RESOLVE_CALL = 50 to avoid O(N^2) LLM
    blow-up (R1 audit hard requirement).
    """
    from src.reconciliation.claim_resolver import (
        MAX_CLAIM_PAIRS_PER_RESOLVE_CALL,
        MAX_EVIDENCE_CHARS,
        build_claim_pair_evidence_pack,
        enumerate_claim_pairs,
    )

    # MAX_CLAIM_PAIRS_PER_RESOLVE_CALL must be exactly 50 (R1 audit).
    assert MAX_CLAIM_PAIRS_PER_RESOLVE_CALL == 50

    # Pair enumeration respects the cap (R1 audit): >50 inputs →
    # capped output, prioritized by shorter total text length first.
    class FakeClaim:
        def __init__(self, claim_id, text):
            self.claim_id = claim_id
            self.text = text
            self.evidence_refs = []

    # 60 claims → 60*59/2 = 1770 candidate pairs; must be capped to 50.
    many_claims = [FakeClaim(f"c-{i:03d}", f"text number {i} " * (i + 1)) for i in range(60)]
    pairs = enumerate_claim_pairs(many_claims, max_pairs=MAX_CLAIM_PAIRS_PER_RESOLVE_CALL)
    assert len(pairs) <= MAX_CLAIM_PAIRS_PER_RESOLVE_CALL

    # Evidence pack for a single pair is bounded per claim.
    a = FakeClaim("a", "x" * 5000)
    b = FakeClaim("b", "y" * 5000)
    pack = build_claim_pair_evidence_pack(
        a,
        b,
        source_bytes={},
    )
    assert "claim_a_excerpt" in pack
    assert "claim_b_excerpt" in pack
    # Truncated body (MAX_EVIDENCE_CHARS) + "..." marker (3 chars).
    assert len(pack["claim_a_excerpt"]) <= MAX_EVIDENCE_CHARS + 3
    assert len(pack["claim_b_excerpt"]) <= MAX_EVIDENCE_CHARS + 3
