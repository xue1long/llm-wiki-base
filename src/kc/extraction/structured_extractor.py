"""Structured Fact extractor (路线 v2.2 §C-4.5 / Z-8, spec §3.5 + §5.6).

Pulls Structured Facts from parameter tables / regulations / code definitions.
Coexists with Claim extraction: Claim and Structured Fact both attach to the
same KU via ``attach_claim`` + ``attach_structured_fact`` (spec §3.5 P-5).

Both paths share Evidence references — StructuredFact.evidence_ids holds
``Evidence.evidence_id`` strings, never the Evidence objects themselves, so
the same Evidence can back multiple facts without duplication.
"""
from __future__ import annotations

from src.kc.contracts.structured_fact import StructuredFact


def extract_structured_facts(
    table_data: list[dict],
    run_id: str,
) -> list[StructuredFact]:
    """Convert a parameter-table-like dict list into StructuredFact objects.

    Each input dict must provide: subject, field, value, value_type, context_id,
    validity_id, confidence, evidence_ids (tuple of str). The factory fills in
    status="candidate", version=1, created_at=0, updated_at=0 by default.
    """
    facts: list[StructuredFact] = []
    for row in table_data:
        facts.append(
            StructuredFact(
                subject=row["subject"],
                field=row["field"],
                value=row["value"],
                value_type=row["value_type"],
                context_id=row.get("context_id"),
                validity_id=row.get("validity_id"),
                confidence=row.get("confidence", 0.0),
                evidence_ids=tuple(row.get("evidence_ids", ())),
                extraction_run_id=run_id,
                status=row.get("status", "candidate"),
                version=row.get("version", 1),
                created_at=row.get("created_at", 0),
                updated_at=row.get("updated_at", 0),
            )
        )
    return facts


class StructuredExtractor:
    """Stateful extractor that batches Structured Facts into KUs.

    spec §3.5 P-5: Claim and Structured Fact both attach to the same KU via
    ``attach_claim`` and ``attach_structured_fact``. Both are kept on the KU
    independently so neither path overwrites the other.
    """

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self._facts: list[StructuredFact] = []
        self._ku_claims: dict[str, dict] = {}
        self._ku_structured_facts: dict[str, list[StructuredFact]] = {}

    # ── Structured Fact ingestion ──────────────────────────────────────

    def add(self, fact: StructuredFact) -> None:
        """Register a StructuredFact without attaching it to a KU yet."""
        self._facts.append(fact)

    def attach_structured_fact(self, kc_ku_id: str, fact: StructuredFact) -> None:
        """Attach a StructuredFact to a KU (spec §3.5 合并到 KU)."""
        self._ku_structured_facts.setdefault(kc_ku_id, []).append(fact)

    # ── Claim ingestion (spec §3.5 双路径) ─────────────────────────────

    def attach_claim(self, kc_ku_id: str, claim: dict) -> None:
        """Attach a Claim to the same KU without disturbing structured facts.

        spec §3.5 P-5: Claim 与 Structured Fact 共享 Evidence/Context/Temporal
        契约，但两者是 KU 上的独立成员，不互相覆盖。
        """
        self._ku_claims[kc_ku_id] = claim

    # ── KU state inspection ────────────────────────────────────────────

    def snapshot_ku(self, kc_ku_id: str) -> dict:
        """Return the current state of a KU as a dict with keys ``claim`` and
        ``structured_facts``. Used by tests + downstream promotion code."""
        return {
            "claim": self._ku_claims.get(kc_ku_id),
            "structured_facts": list(self._ku_structured_facts.get(kc_ku_id, [])),
        }

    @property
    def all_facts(self) -> list[StructuredFact]:
        return list(self._facts)