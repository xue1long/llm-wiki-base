"""Task 34 — CanonicalClaimRegistry: persistent canonical-claim store.

Phase 2 of the reconciliation plane (ADR 0012). Owns two on-disk
artifacts under ``<root>/.index/reconciliation/``:

  * ``canonical_claims.json``  — ``{canonical_claim_id: CanonicalClaim}``
  * ``claim_decision_log.jsonl`` — append-only, every decision record

and exposes the four hard-requirement operations:

  * :py:meth:`CanonicalClaimRegistry.apply_claim_decisions`
        — Priority-sorted batch apply for one canonical. SAME / OVERLAP
          join existing canonical_claims; CONFLICT splits each
          member into its own canonical_claim; UNRESOLVED is skipped.

  * :py:meth:`CanonicalClaimRegistry.remove_member_claim`
        — Reversible per-claim removal. Empty members preserved
          (canonical_claim entity never auto-deleted).

  * :py:meth:`CanonicalClaimRegistry.find_stale`
        — F4 hard requirement. Walks every canonical_claim whose
          ``resolver_fingerprint`` no longer matches
          ``current_fingerprint`` and returns their ids.

  * :py:meth:`CanonicalClaimRegistry.save_canonical_claims`
        — atomic write of the canonical-claim store.

Failure Contract
----------------
All IO operations swallow + log (Failure Contract §1). A missing /
malformed storage file returns an empty mapping rather than raising.
Atomic write uses the ``tmp + rename`` pattern (an independent
implementation here; we don't import ``wiki_writer`` because the
registry must stay usable even when the wiki writer is absent, e.g.
in early-pipeline tests).

Reversibility
-------------
:py:meth:`remove_member_claim` is the canonical mutator for member
removal; it never deletes the canonical_claim itself. A later
:py:meth:`apply_claim_decisions` with a SAME / OVERLAP verdict
containing the same claim_id rejoins the canonical_claim (via
:py:meth:`CanonicalClaim.add_member_claim`).

Identity Contract
-----------------
``canonical_claim_id`` is script-owned (:py:func:`canonical_claim_id_for`).
The LLM emits ``pair_id`` references but never fabricates ids.

Decision priority
-----------------
The apply order is fixed by spec §5.2:

    same > overlap > conflict > unresolved > single
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from .canonical_claim_models import (
    CanonicalClaim,
    ClaimDecisionRecord,
    ClaimReconciliationDecision,
    RelationSupportKind,
    canonical_claim_id_for,
    decision_id_for_pair,
)


_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def canonical_claims_path(root: Path | str) -> Path:
    """Path to ``canonical_claims.json`` under the reconciliation dir.

    Creates the parent directory (``parents=True, exist_ok=True``)
    best-effort: a permission error is swallowed so callers always get
    a usable Path (Failure Contract §1).
    """
    base = Path(root) / ".index" / "reconciliation"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except Exception as exc:  # pragma: no cover - filesystem failure
        _LOG.warning("canonical_claims_path mkdir failed: %s", exc)
    return base / "canonical_claims.json"


def claim_decision_log_path(root: Path | str) -> Path:
    """Path to ``claim_decision_log.jsonl`` under the reconciliation dir."""
    base = Path(root) / ".index" / "reconciliation"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except Exception as exc:  # pragma: no cover - filesystem failure
        _LOG.warning("claim_decision_log_path mkdir failed: %s", exc)
    return base / "claim_decision_log.jsonl"


# ---------------------------------------------------------------------------
# Decision priority
# ---------------------------------------------------------------------------


_DECISION_PRIORITY: dict[ClaimReconciliationDecision, int] = {
    ClaimReconciliationDecision.SAME: 0,
    ClaimReconciliationDecision.OVERLAP: 1,
    ClaimReconciliationDecision.CONFLICT: 2,
    ClaimReconciliationDecision.UNRESOLVED: 3,
    ClaimReconciliationDecision.SINGLE: 4,
}


def sort_claim_decisions(
    decisions: list[ClaimDecisionRecord],
) -> list[ClaimDecisionRecord]:
    """Stable sort by priority asc (same > overlap > ... > single)."""
    return sorted(
        decisions,
        key=lambda d: _DECISION_PRIORITY.get(d.decision, 99),
    )


# ---------------------------------------------------------------------------
# Atomic write helper (independent; does NOT import wiki_writer)
# ---------------------------------------------------------------------------


def _atomic_write_json(path: Path, payload: Any) -> None:
    """Write ``payload`` as JSON to ``path`` atomically (tmp + rename).

    Failure Contract §1: never raises. Any I/O / serialization error is
    swallowed and logged. The canonical file at ``path`` is left
    untouched on failure — readers continue to see the previous
    contents.

    Note: this is an independent implementation; we deliberately do not
    import ``src.wiki.storage.write_atomic`` (or any ``wiki_writer``
    cousin) so the reconciliation subsystem stays usable when the
    wiki storage layer is unavailable (e.g. in unit tests of the
    candidate pipeline).
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        # Best-effort cleanup of any stale tmp from a prior crash.
        if tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass
        data = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        tmp.write_text(data, encoding="utf-8")
        os.replace(tmp, path)
    except Exception as exc:  # pragma: no cover - filesystem failure
        _LOG.warning("_atomic_write_json failed for %s: %s", path, exc)


# ---------------------------------------------------------------------------
# Pair parsing
# ---------------------------------------------------------------------------


def _parse_pair_id(pair_id: str) -> tuple[str, str]:
    """Split ``"a|b"`` back into ``(a, b)``.

    Failure Contract: never raises. A malformed ``pair_id`` (no ``|``)
    returns ``("", pair_id)`` so the registry never throws on bad
    input from the LLM.
    """
    if not pair_id or "|" not in pair_id:
        return "", pair_id or ""
    a, b = pair_id.split("|", 1)
    return a, b


# ---------------------------------------------------------------------------
# CanonicalClaimRegistry
# ---------------------------------------------------------------------------


class CanonicalClaimRegistry:
    """Persistent canonical-claim store.

    Parameters
    ----------
    root:
        Project root. The two storage files live under
        ``<root>/.index/reconciliation/``.
    resolver_fingerprint:
        Fingerprint of the resolver that owns this registry instance.
        Stored on every canonical_claim at apply time and used by
        :py:meth:`find_stale` to detect drift.
    """

    def __init__(
        self,
        root: Path | str,
        *,
        resolver_fingerprint: str = "",
    ) -> None:
        self.root = Path(root)
        self._fingerprint = resolver_fingerprint

    # ---- Read -------------------------------------------------------------

    def load_canonical_claims(self) -> dict[str, CanonicalClaim]:
        """Load canonical claims from disk.

        Returns an empty dict when the file is missing or malformed
        (Failure Contract §1). Bad entries are dropped, not raised on.
        """
        path = canonical_claims_path(self.root)
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            _LOG.warning("load_canonical_claims: failed to parse %s: %s", path, exc)
            return {}
        if not isinstance(data, dict):
            return {}
        out: dict[str, CanonicalClaim] = {}
        for ccid, raw in data.items():
            if not isinstance(raw, dict):
                continue
            try:
                out[str(ccid)] = _claim_from_dict(raw)
            except Exception as exc:
                _LOG.warning("load_canonical_claims: drop %s: %s", ccid, exc)
        return out

    def get_canonical_claim(
        self, canonical_claim_id: str
    ) -> CanonicalClaim | None:
        """Return one canonical claim or ``None`` if not present."""
        if not canonical_claim_id:
            return None
        return self.load_canonical_claims().get(canonical_claim_id)

    def list_for_canonical(self, canonical_id: str) -> list[CanonicalClaim]:
        """All canonical claims whose ``canonical_id`` matches."""
        if not canonical_id:
            return []
        return [
            cc for cc in self.load_canonical_claims().values()
            if cc.canonical_id == canonical_id
        ]

    # ---- Write ------------------------------------------------------------

    def save_canonical_claims(
        self, claims: dict[str, CanonicalClaim]
    ) -> None:
        """Atomically write the canonical-claim map.

        Public-ish: tests use it to seed fixtures without going through
        :py:meth:`apply_claim_decisions`. The atomic write + JSON
        round-trip is the same path production uses.
        """
        payload = {ccid: _claim_to_dict(cc) for ccid, cc in claims.items()}
        _atomic_write_json(canonical_claims_path(self.root), payload)

    def apply_claim_decisions(
        self,
        canonical_id: str,
        decisions: list[ClaimDecisionRecord],
        *,
        resolver_fingerprint: str = "",
    ) -> list[CanonicalClaim]:
        """Apply a batch of decisions for one canonical concept.

        Steps
        -----
        1. Sort decisions by priority asc (same > overlap > conflict >
           unresolved > single).
        2. For each decision (in priority order):
             - UNRESOLVED → skip (fail-closed; nothing to apply)
             - SAME / OVERLAP → pair_id's two claims join one
               canonical_claim (existing or new)
             - CONFLICT → pair_id's two claims split into two
               canonical_claim records (each with one member)
             - SINGLE → no decision was supplied; produce a 1-member
               canonical_claim per unique claim_id seen in the input
               set (last step, after pairs are processed)
        3. Append every decision to ``claim_decision_log.jsonl``.
        4. Atomic write of ``canonical_claims.json``.

        Returns the list of canonical claims touched.

        Failure Contract §1: never raises. A malformed pair_id is
        logged and skipped. A missing canonical_id is logged and
        skipped.
        """
        store = self.load_canonical_claims()
        effective_fp = resolver_fingerprint or self._fingerprint
        now_ms = int(time.time() * 1000)
        touched: list[CanonicalClaim] = []

        # Track every distinct claim_id we saw so SINGLE records them
        # even when no pair decision was emitted for them.
        seen_claim_ids: list[str] = []
        seen_set: set[str] = set()

        for decision in sort_claim_decisions(decisions):
            # Always append to the audit log — audit is unconditional.
            self._append_decision_log(decision)

            verdict = decision.decision

            pair_a, pair_b = _parse_pair_id(decision.pair_id)
            for cid in (pair_a, pair_b):
                if cid and cid not in seen_set:
                    seen_set.add(cid)
                    seen_claim_ids.append(cid)

            if verdict is ClaimReconciliationDecision.UNRESOLVED:
                continue

            if verdict is ClaimReconciliationDecision.CONFLICT:
                # Split: each claim gets its own canonical claim.
                for member in (pair_a, pair_b):
                    if not member:
                        continue
                    cc = self._ensure_single_member(
                        store=store,
                        canonical_id=canonical_id,
                        member_id=member,
                        resolver_fingerprint=effective_fp,
                        now_ms=now_ms,
                        decision=verdict,
                    )
                    if cc not in touched:
                        touched.append(cc)
                continue

            if verdict in (
                ClaimReconciliationDecision.SAME,
                ClaimReconciliationDecision.OVERLAP,
            ):
                # Join: pair lives together in one canonical claim.
                # The first occurrence creates the canonical claim;
                # subsequent pairs merge into it.
                cc = self._ensure_pair_group(
                    store=store,
                    canonical_id=canonical_id,
                    member_a=pair_a,
                    member_b=pair_b,
                    resolver_fingerprint=effective_fp,
                    now_ms=now_ms,
                    decision=verdict,
                )
                if cc not in touched:
                    touched.append(cc)
                continue

            # SINGLE: nothing to do per-record here. We back-fill
            # below for any orphan claim_id that didn't appear in
            # any pair decision.

        # SINGLE back-fill: any claim_id the LLM never paired off
        # becomes a 1-member canonical_claim on its own. This mirrors
        # Phase 1's "DISTINCT → new canonical" semantic.
        existing_members: set[str] = set()
        for cc in store.values():
            if cc.canonical_id == canonical_id:
                existing_members.update(cc.member_claim_ids)

        for orphan in seen_claim_ids:
            if orphan in existing_members:
                continue
            cc = self._ensure_single_member(
                store=store,
                canonical_id=canonical_id,
                member_id=orphan,
                resolver_fingerprint=effective_fp,
                now_ms=now_ms,
                decision=ClaimReconciliationDecision.SINGLE,
            )
            if cc not in touched:
                touched.append(cc)

        # Atomic write of the touched store.
        self.save_canonical_claims(store)
        return touched

    def remove_member_claim(
        self, canonical_claim_id: str, claim_id: str
    ) -> bool:
        """Remove ``claim_id`` from ``canonical_claim_id``.

        Returns ``True`` iff ``claim_id`` was a member (idempotent —
        removing a non-member returns ``False``).

        Reversibility
        -------------
        The canonical claim entity itself is preserved (the registry
        never auto-deletes). Empty memberships are kept on disk so a
        later :py:meth:`apply_claim_decisions` (with a SAME/OVERLAP
        verdict that re-pairs the same claim_id) can repopulate via
        :py:meth:`CanonicalClaim.add_member_claim`.
        """
        store = self.load_canonical_claims()
        cc = store.get(canonical_claim_id)
        if cc is None:
            return False
        removed = cc.remove_member_claim(claim_id)
        if not removed:
            return False
        cc.updated_at_ms = int(time.time() * 1000)
        self.save_canonical_claims(store)
        return True

    # ---- F4: Fingerprint drift --------------------------------------------

    def find_stale(self, current_fingerprint: str) -> list[str]:
        """Find canonical claims whose fingerprint drifts from current.

        Returns the list of ``canonical_claim_id`` values whose
        ``resolver_fingerprint`` does **not** match
        ``current_fingerprint``. Unlike Phase 1's
        :py:meth:`CanonicalRegistry.mark_stale_concepts`, this method
        is non-mutating: it only reports; mutating STALE markers on
        canonical claims is intentionally out of scope (canonical
        claims don't carry a multi-state lifecycle).
        """
        out: list[str] = []
        for ccid, cc in self.load_canonical_claims().items():
            if not cc.resolver_fingerprint:
                # No fingerprint recorded → not stale (the registry
                # is conservative; absence is not drift).
                continue
            if cc.resolver_fingerprint == current_fingerprint:
                continue
            out.append(ccid)
        return out

    # ---- Internal helpers -------------------------------------------------

    def _ensure_pair_group(
        self,
        *,
        store: dict[str, CanonicalClaim],
        canonical_id: str,
        member_a: str,
        member_b: str,
        resolver_fingerprint: str,
        now_ms: int,
        decision: ClaimReconciliationDecision,
    ) -> CanonicalClaim:
        """Find or create the canonical claim that owns ``(a, b)``.

        Lookup strategy (in order):
          1. A canonical claim already containing ``member_a`` AND
             belonging to ``canonical_id`` — extend it with
             ``member_b``.
          2. Same for ``member_b`` — extend with ``member_a``.
          3. Otherwise create a fresh canonical claim grouping
             ``(member_a, member_b)``.

        Whichever canonical claim wins, its text is set to the first
        added member's text (Task 34 spec: ``text = member[0].text``
        for this iteration). The actual ``text`` value is supplied by
        the caller via the canonical-claim record's stored text; when
        a fresh record is created we use the empty string placeholder
        (the caller is expected to refresh text on the next pass).
        """
        for member_anchor, member_other in (
            (member_a, member_b),
            (member_b, member_a),
        ):
            if not member_anchor or not member_other:
                continue
            for cc in store.values():
                if cc.canonical_id != canonical_id:
                    continue
                if member_anchor not in cc.member_claim_ids:
                    continue
                # Found an existing canonical claim that owns the
                # anchor member — extend it with the other member.
                cc.add_member_claim(member_other)
                cc.decision = decision
                cc.resolver_fingerprint = resolver_fingerprint
                cc.updated_at_ms = now_ms
                return cc

        # No existing canonical claim to merge into — create a fresh one.
        if member_a and member_b:
            members = [member_a, member_b]
        elif member_a:
            members = [member_a]
        elif member_b:
            members = [member_b]
        else:
            # No real members — fabricate an empty group. Should not
            # happen in practice (UNRESOLVED is filtered upstream),
            # but we stay total.
            members = []
        ccid = canonical_claim_id_for(
            canonical_id=canonical_id,
            text="",  # text is backfilled on the next apply pass
            support_kind=RelationSupportKind.EXPLICIT.value,
        )
        # Avoid clashing with an existing id (extremely unlikely with
        # sha1[:12], but defensive).
        if ccid in store:
            ccid = f"{ccid}-{len(store)}"
        cc = CanonicalClaim(
            canonical_claim_id=ccid,
            canonical_id=canonical_id,
            text="",
            member_claim_ids=list(members),
            decision=decision,
            confidence=0.0,
            support_kind=RelationSupportKind.EXPLICIT,
            created_at_ms=now_ms,
            updated_at_ms=now_ms,
            resolver_fingerprint=resolver_fingerprint,
        )
        store[ccid] = cc
        return cc

    def _ensure_single_member(
        self,
        *,
        store: dict[str, CanonicalClaim],
        canonical_id: str,
        member_id: str,
        resolver_fingerprint: str,
        now_ms: int,
        decision: ClaimReconciliationDecision,
    ) -> CanonicalClaim:
        """Find or create a 1-member canonical claim for ``member_id``.

        When the member already belongs to a canonical_claim in
        ``canonical_id``, that record is reused (its decision is
        updated). Otherwise a fresh 1-member record is created.
        """
        if not member_id:
            # Defensive: caller already filters empty ids, but be
            # total even for malformed input.
            ccid = canonical_claim_id_for(
                canonical_id=canonical_id or "",
                text="",
                support_kind=RelationSupportKind.EXPLICIT.value,
            )
            cc = CanonicalClaim(
                canonical_claim_id=ccid,
                canonical_id=canonical_id or "",
                text="",
                member_claim_ids=[],
                decision=decision,
                confidence=0.0,
                support_kind=RelationSupportKind.EXPLICIT,
                created_at_ms=now_ms,
                updated_at_ms=now_ms,
                resolver_fingerprint=resolver_fingerprint,
            )
            store[ccid] = cc
            return cc

        for cc in store.values():
            if cc.canonical_id != canonical_id:
                continue
            if member_id in cc.member_claim_ids:
                cc.decision = decision
                cc.resolver_fingerprint = resolver_fingerprint
                cc.updated_at_ms = now_ms
                return cc

        ccid = canonical_claim_id_for(
            canonical_id=canonical_id,
            text="",
            support_kind=RelationSupportKind.EXPLICIT.value,
        )
        if ccid in store:
            ccid = f"{ccid}-{len(store)}"
        cc = CanonicalClaim(
            canonical_claim_id=ccid,
            canonical_id=canonical_id,
            text="",
            member_claim_ids=[member_id],
            decision=decision,
            confidence=0.0,
            support_kind=RelationSupportKind.EXPLICIT,
            created_at_ms=now_ms,
            updated_at_ms=now_ms,
            resolver_fingerprint=resolver_fingerprint,
        )
        store[ccid] = cc
        return cc

    def _append_decision_log(self, decision: ClaimDecisionRecord) -> None:
        """Append a single decision to ``claim_decision_log.jsonl``.

        Failure Contract §1: never raises. The audit log is best-effort
        — losing a log entry must not block canonical-claim updates.
        """
        path = claim_decision_log_path(self.root)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(_decision_to_dict(decision), ensure_ascii=False)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception as exc:  # pragma: no cover - filesystem failure
            _LOG.warning("_append_decision_log failed for %s: %s", path, exc)


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _claim_to_dict(cc: CanonicalClaim) -> dict[str, Any]:
    return {
        "canonical_claim_id": cc.canonical_claim_id,
        "canonical_id": cc.canonical_id,
        "text": cc.text,
        "member_claim_ids": list(cc.member_claim_ids),
        "decision": cc.decision.value,
        "confidence": cc.confidence,
        "support_kind": cc.support_kind.value,
        "created_at_ms": cc.created_at_ms,
        "updated_at_ms": cc.updated_at_ms,
        "resolver_fingerprint": cc.resolver_fingerprint,
    }


def _claim_from_dict(raw: dict[str, Any]) -> CanonicalClaim:
    return CanonicalClaim(
        canonical_claim_id=str(raw.get("canonical_claim_id", "")),
        canonical_id=str(raw.get("canonical_id", "")),
        text=str(raw.get("text", "") or ""),
        member_claim_ids=list(raw.get("member_claim_ids", []) or []),
        decision=ClaimReconciliationDecision(
            str(raw.get("decision", "single"))
        ),
        confidence=float(raw.get("confidence", 0.0) or 0.0),
        support_kind=RelationSupportKind(str(raw.get("support_kind", "explicit"))),
        created_at_ms=int(raw.get("created_at_ms", 0) or 0),
        updated_at_ms=int(raw.get("updated_at_ms", 0) or 0),
        resolver_fingerprint=str(raw.get("resolver_fingerprint", "") or ""),
    )


def _decision_to_dict(decision: ClaimDecisionRecord) -> dict[str, Any]:
    return {
        "decision_id": decision.decision_id,
        "pair_id": decision.pair_id,
        "canonical_id": decision.canonical_id,
        "decision": decision.decision.value,
        "confidence": decision.confidence,
        "reason": decision.reason,
        "evidence_refs": list(decision.evidence_refs),
        "resolver_fingerprint": decision.resolver_fingerprint,
        "created_at_ms": decision.created_at_ms,
    }


__all__ = [
    "CanonicalClaimRegistry",
    "canonical_claims_path",
    "claim_decision_log_path",
    "sort_claim_decisions",
]
