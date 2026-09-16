"""Task 29 — Identity resolver + LLM-only-decision contract.

Three RED probes (each a contract assertion):

  * test_llm_only_returns_decision_not_canonical_id
        — ``parse_llm_verdicts`` is the trust boundary: LLM only emits
          ``(canonical_id, decision, confidence, reason)`` and the script
          derives ``decision_id`` from the deterministic hash. Verifies
          that the script-generated id starts with ``dec-`` and the LLM
          cannot influence id generation.

  * test_llm_technical_failure_returns_unresolved
        — When the LLM provider raises on every retry, every candidate
          receives an ``UNRESOLVED`` verdict (fail-closed, never raises
          from the public entry point).

  * test_evidence_pack_is_controlled_not_whole_page
        — ``build_evidence_pack`` respects the bounded-evidence contract:
          each key slot is truncated to ``MAX_KEY_SLOT_CHARS`` and the
          total body evidence is truncated to ``MAX_EVIDENCE_CHARS``. The
          LLM never sees the whole page.

Contract summary (see identity_resolver.py docstring):
    MAX_KEY_SLOT_CHARS = 600
    MAX_EVIDENCE_CHARS  = 1500
    Identity Contract: LLM emits (canonical_id, decision, confidence,
                             reason) only; script owns decision_id.
    Failure Contract §1: never raises; technical failure → UNRESOLVED.
    canonical_id whitelist: parse_llm_verdicts drops any verdict whose
                            canonical_id is not in the candidate list.
"""
from __future__ import annotations

import json


def test_llm_only_returns_decision_not_canonical_id():
    """LLM 输出只有 decision + canonical_id (从候选列表复制);脚本生成 decision_id。

    parse_llm_verdicts must:
      * coerce the raw JSON into ReconciliationDecisionRecord
      * set decision_id via sha1 of (page_id|canonical_id|decision)
      * not depend on any LLM-provided decision_id field
    """
    from src.reconciliation.identity_resolver import parse_llm_verdicts
    from src.reconciliation.candidate_retrieval import ReconciliationCandidate
    from src.reconciliation.canonical_models import ReconciliationDecision

    cid_a = "c-1234567890123456"  # fixed so the hash is reproducible
    candidates = [
        ReconciliationCandidate(
            canonical_id=cid_a, score=1.0, strategy="explicit", detail="wikilink"
        ),
    ]

    raw = json.dumps({
        "verdicts": [
            {"canonical_id": cid_a, "decision": "same", "confidence": 0.9, "reason": "ok"},
        ]
    })
    decisions = parse_llm_verdicts(
        raw,
        new_page_id="page-x",
        candidates=candidates,
        resolver_fingerprint="fp-test",
    )

    assert len(decisions) == 1
    d = decisions[0]
    assert d.decision is ReconciliationDecision.SAME
    assert d.candidate_canonical_id == cid_a
    # decision_id is script-generated (sha1 prefix), never provided by LLM
    assert d.decision_id.startswith("dec-")
    assert d.resolver_fingerprint == "fp-test"
    # new_page_id is wired into the record (candidate_page_id is the page id,
    # not the candidate canonical id)
    assert d.candidate_page_id == "page-x"


def test_llm_technical_failure_returns_unresolved():
    """LLM 全部重试抛异常 → 所有 candidates 标 UNRESOLVED (fail-closed)。

    resolve_identity must never raise. When the underlying LLM provider
    raises on every retry attempt, every candidate receives an UNRESOLVED
    verdict so the caller can still proceed (UNRESOLVED is the design choice
    for "technical failure", per Failure Contract §1).
    """
    import asyncio

    from src.reconciliation.identity_resolver import resolve_identity
    from src.reconciliation.candidate_retrieval import (
        CanonicalIndex,
        ReconciliationCandidate,
    )
    from src.reconciliation.canonical_models import ReconciliationDecision

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

    cid_a = "c-aaa"
    cid_b = "c-bbb"
    candidates = [
        ReconciliationCandidate(
            canonical_id=cid_a, score=1.0, strategy="explicit", detail="x"
        ),
        ReconciliationCandidate(
            canonical_id=cid_b, score=0.8, strategy="entity_overlap", detail="y"
        ),
    ]

    decisions = asyncio.run(
        resolve_identity(
            "page-x",
            "Title",
            None,
            candidates,
            CanonicalIndex(),
            llm=FailingLLM(),
            resolver_fingerprint="fp-test",
        )
    )

    assert len(decisions) == 2
    for d in decisions:
        assert d.decision is ReconciliationDecision.UNRESOLVED
        assert d.candidate_canonical_id in {cid_a, cid_b}


def test_evidence_pack_is_controlled_not_whole_page():
    """evidence pack 受 bounded,不暴露整 page。

    build_evidence_pack must enforce:
      * each key slot is truncated to ``MAX_KEY_SLOT_CHARS``
      * the body evidence is truncated to ``MAX_EVIDENCE_CHARS``
      * the LLM never sees the whole page body
    """
    from src.reconciliation.identity_resolver import (
        build_evidence_pack,
        MAX_EVIDENCE_CHARS,
        MAX_KEY_SLOT_CHARS,
    )

    class P:
        pass

    p = P()
    p.id = "page-x"
    p.title = "Test"
    p.slots = {
        "definition": "x" * 5000,         # >> MAX_KEY_SLOT_CHARS
        "characteristics": "y" * 1000,    # >> MAX_KEY_SLOT_CHARS
    }
    p.body = "z" * 10000                   # >> MAX_EVIDENCE_CHARS

    pack = build_evidence_pack(p, body_by_page={"page-x": p.body})

    assert "key_slots_text" in pack
    assert "evidence_text" in pack
    # Two key slots, each capped at MAX_KEY_SLOT_CHARS, plus a small
    # label overhead ("definition: " / "characteristics: ") and the
    # " | " separator. The test asserts the upper bound is well below
    # the un-truncated total (5000 + 1000 + ~20 bytes of overhead).
    assert len(pack["key_slots_text"]) <= MAX_KEY_SLOT_CHARS * 2 + 50
    # evidence_text: truncated to MAX_EVIDENCE_CHARS plus a small
    # truncation marker ("..."), well below the un-truncated 10000.
    assert len(pack["evidence_text"]) <= MAX_EVIDENCE_CHARS + 100