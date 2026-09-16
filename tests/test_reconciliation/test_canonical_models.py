"""Task 27 — canonical_models dataclasses + Decision enum.

Three RED probes (each is a contract assertion):
  * test_canonical_id_format_is_uuid_based — Identity Contract
  * test_reconciliation_decision_enum_has_eight_values — Vocabulary Contract
  * test_aliasrecord_supports_multilingual — Multilingual Alias Contract

The dataclasses themselves (`CanonicalConcept`, `AliasRecord`,
`ReconciliationDecisionRecord`) are exercised indirectly through the
probes plus the public surface documented in the task spec. Additional
behaviour (apply_decisions, member membership transitions, slug
adapter) is added by later tasks (28 / 30).
"""
from __future__ import annotations


def test_canonical_id_format_is_uuid_based():
    """canonical_id 是 c-<uuid4_hex[:16]>，script-owned"""
    from src.reconciliation.canonical_models import new_canonical_id

    ids = {new_canonical_id() for _ in range(100)}
    assert len(ids) == 100  # uuid4 unique
    for cid in ids:
        assert cid.startswith("c-")
        assert len(cid) == len("c-") + 16
        # hex chars only
        int(cid[2:], 16)  # raises if non-hex


def test_reconciliation_decision_enum_has_eight_values():
    """ReconciliationDecision 8 个值 + UNRESOLVED 是合法 decision"""
    from src.reconciliation.canonical_models import ReconciliationDecision

    expected = {
        "same",
        "alias",
        "broader",
        "narrower",
        "overlap",
        "conflict",
        "distinct",
        "unresolved",
    }
    actual = {d.value for d in ReconciliationDecision}
    assert actual == expected
    # UNRESOLVED is a valid value (not an exception)
    assert ReconciliationDecision("unresolved") is ReconciliationDecision.UNRESOLVED


def test_aliasrecord_supports_multilingual():
    """AliasRecord 接受多语言 alias_text（en/zh/ja）"""
    from src.reconciliation.canonical_models import AliasRecord, new_canonical_id

    cid = new_canonical_id()
    aliases = [
        AliasRecord(alias_text="RAG", canonical_id=cid, language="en"),
        AliasRecord(alias_text="检索增强生成", canonical_id=cid, language="zh"),
        AliasRecord(
            alias_text="Retrieval-Augmented Generation",
            canonical_id=cid,
            language="en",
        ),
        AliasRecord(alias_text="検索拡張生成", canonical_id=cid, language="ja"),
    ]
    # 4 个 alias 都接受，没拒
    assert all(a.canonical_id == cid for a in aliases)
    assert {a.language for a in aliases} == {"en", "zh", "ja"}