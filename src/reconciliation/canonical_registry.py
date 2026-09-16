"""Task 30 — Canonical registry: persistent canonical concept store.

The :class:`CanonicalRegistry` is the durable backbone of the
reconciliation subsystem (Tasks 27-32 of the v7 stage remediation
plan). It owns three on-disk artifacts under
``<root>/.index/reconciliation/``:

  * ``canonical_concepts.json`` — ``{canonical_id: CanonicalConcept}``
  * ``alias_records.json``      — ``{(alias_text, language): AliasRecord}``
  * ``decision_log.jsonl``      — append-only, every decision recorded

and exposes the four hard-requirement operations:

  * :py:meth:`CanonicalRegistry.apply_decisions`
        — Priority-sorted batch apply for one new page. DISTINCT
          creates a new canonical; SAME / ALIAS / etc. join an existing
          one and update ``resolver_fingerprint`` (F4).

  * :py:meth:`CanonicalRegistry.remove_membership`
        — Reversible member removal. Last-member-out transitions the
          canonical to ``TOMBSTONED`` but keeps its aliases so the
          record survives.

  * :py:meth:`CanonicalRegistry.mark_stale_concepts`
        — F4 hard requirement. Walks every ACTIVE canonical and
          transitions it to ``STALE`` when ``resolver_fingerprint`` no
          longer matches the current resolver.

  * :py:meth:`CanonicalRegistry.add_alias`
        — F15 hard requirement. The **only** sanctioned write path for
          aliases. Internally forwards to the
          :py:class:`SlugAliasRegistryAdapter` so
          ``.llm-wiki/slug_aliases.json`` stays in sync.

Failure Contract
----------------
All IO operations swallow + log (Failure Contract §1). A missing /
malformed storage file returns an empty mapping rather than raising.
Atomic write uses the ``tmp + rename`` pattern — a crash mid-write
leaves either the old file intact or the new file in place, never a
half-written file at the canonical path.

Reversibility
-------------
:py:meth:`remove_membership` is the canonical mutator for member
removal; it never deletes the canonical concept itself or its aliases.
A later :py:meth:`apply_decisions` with the same page_id rejoins the
canonical (idempotent :py:meth:`CanonicalConcept.add_member`). This is
how ``reconcile --undo`` (Task 31) implements reversible membership.

Identity Contract
-----------------
``canonical_id`` is script-owned (:py:func:`new_canonical_id`). The LLM
emits ``candidate_canonical_id`` references but never fabricates ids.

Decision priority
-----------------
The apply order is fixed by the spec (F4 acceptance — "应用顺序"):

    same > alias > conflict > overlap > broader > narrower >
    distinct > unresolved

Ties within a priority bucket are processed in the LLM's input order
(stable sort).
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from .canonical_models import (
    AliasRecord,
    CanonicalConcept,
    ReconciliationDecision,
    ReconciliationDecisionRecord,
    ReconciliationStatus,
    SlugAliasRegistryAdapter,
    new_canonical_id,
)


_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def reconciliation_dir(root: Path | str) -> Path:
    """Return the reconciliation directory under ``root``.

    Creates it (``parents=True, exist_ok=True``) so callers can write
    files immediately after. Failure Contract §1: a permission error
    is swallowed and logged — the caller still gets a usable Path,
    even if subsequent writes silently fail.
    """
    p = Path(root) / ".index" / "reconciliation"
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception as exc:  # pragma: no cover - filesystem failure
        _LOG.warning("reconciliation_dir mkdir failed: %s", exc)
    return p


def canonical_concepts_path(root: Path | str) -> Path:
    """Path to ``canonical_concepts.json`` under the reconciliation dir."""
    return reconciliation_dir(root) / "canonical_concepts.json"


def alias_records_path(root: Path | str) -> Path:
    """Path to ``alias_records.json`` under the reconciliation dir."""
    return reconciliation_dir(root) / "alias_records.json"


def decision_log_path(root: Path | str) -> Path:
    """Path to ``decision_log.jsonl`` under the reconciliation dir."""
    return reconciliation_dir(root) / "decision_log.jsonl"


# ---------------------------------------------------------------------------
# Decision priority
# ---------------------------------------------------------------------------


_DECISION_PRIORITY: dict[ReconciliationDecision, int] = {
    ReconciliationDecision.SAME: 0,
    ReconciliationDecision.ALIAS: 1,
    ReconciliationDecision.CONFLICT: 2,
    ReconciliationDecision.OVERLAP: 3,
    ReconciliationDecision.BROADER: 4,
    ReconciliationDecision.NARROWER: 5,
    ReconciliationDecision.DISTINCT: 6,
    ReconciliationDecision.UNRESOLVED: 7,
}


def sort_decisions(
    decisions: list[ReconciliationDecisionRecord],
) -> list[ReconciliationDecisionRecord]:
    """Stable sort by priority asc (same > alias > ... > unresolved)."""
    return sorted(
        decisions,
        key=lambda d: _DECISION_PRIORITY.get(d.decision, 99),
    )


# ---------------------------------------------------------------------------
# Atomic write helper
# ---------------------------------------------------------------------------


def _atomic_write_json(path: Path, payload: Any) -> None:
    """Write ``payload`` as JSON to ``path`` atomically (tmp + rename).

    Failure Contract §1: never raises. Any I/O / serialization error is
    swallowed and logged. The canonical file at ``path`` is left
    untouched on failure — readers continue to see the previous
    contents.
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
# CanonicalRegistry
# ---------------------------------------------------------------------------


class CanonicalRegistry:
    """Persistent reconciliation registry.

    Parameters
    ----------
    root:
        Project root. The three storage files live under
        ``<root>/.index/reconciliation/``.
    slug_registry:
        Optional :py:class:`SlugAliasRegistry` instance (or duck-type
        exposing ``register(alias_text=..., canonical_id=...)``).
        When provided, :py:meth:`add_alias` forwards to it via the
        :py:class:`SlugAliasRegistryAdapter`. F15 hard requirement.
    resolver_fingerprint:
        Fingerprint of the resolver that owns this registry instance.
        Stored on every canonical at apply time and used by
        :py:meth:`mark_stale_concepts` to detect drift.
    """

    def __init__(
        self,
        root: Path | str,
        *,
        slug_registry: Any | None = None,
        resolver_fingerprint: str = "",
    ) -> None:
        self.root = Path(root)
        self._fingerprint = resolver_fingerprint
        self._adapter = SlugAliasRegistryAdapter(slug_registry=slug_registry)

    # ---- Read -------------------------------------------------------------

    def load_concepts(self) -> dict[str, CanonicalConcept]:
        """Load canonical concepts from disk.

        Returns an empty dict when the file is missing or malformed
        (Failure Contract §1). Bad entries are dropped, not raised on.
        """
        path = canonical_concepts_path(self.root)
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            _LOG.warning("load_concepts: failed to parse %s: %s", path, exc)
            return {}
        if not isinstance(data, dict):
            return {}
        out: dict[str, CanonicalConcept] = {}
        for cid, raw in data.items():
            if not isinstance(raw, dict):
                continue
            try:
                out[str(cid)] = _concept_from_dict(raw)
            except Exception as exc:
                _LOG.warning("load_concepts: drop %s: %s", cid, exc)
        return out

    def load_aliases(self) -> dict[tuple[str, str], AliasRecord]:
        """Load alias records. Key = ``(alias_text, language)``.

        Returns an empty dict when the file is missing or malformed.
        """
        path = alias_records_path(self.root)
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            _LOG.warning("load_aliases: failed to parse %s: %s", path, exc)
            return {}
        if not isinstance(data, dict):
            return {}
        out: dict[tuple[str, str], AliasRecord] = {}
        for key, raw in data.items():
            if not isinstance(raw, dict):
                continue
            try:
                alias_text, language = _unpack_alias_key(key)
                record = AliasRecord(
                    alias_text=alias_text,
                    canonical_id=str(raw.get("canonical_id", "")),
                    language=language,
                    provenance=str(raw.get("provenance", "")),
                    resolver_fingerprint=str(
                        raw.get("resolver_fingerprint", "")
                    ),
                    created_at_ms=int(raw.get("created_at_ms", 0) or 0),
                )
                out[(alias_text, language)] = record
            except Exception as exc:
                _LOG.warning("load_aliases: drop %s: %s", key, exc)
        return out

    def get_concept(self, canonical_id: str) -> CanonicalConcept | None:
        """Return the canonical concept or ``None`` if not present."""
        if not canonical_id:
            return None
        concepts = self.load_concepts()
        return concepts.get(canonical_id)

    def get_by_alias(
        self, alias_text: str, language: str = ""
    ) -> CanonicalConcept | None:
        """Resolve ``alias_text`` (in ``language``) → canonical concept.

        O(1) via the ``alias_records.json`` map. Returns ``None`` when
        the alias is not registered or its ``canonical_id`` no longer
        exists in the canonical store.
        """
        if not alias_text:
            return None
        aliases = self.load_aliases()
        record = aliases.get((alias_text, language))
        if record is None:
            return None
        return self.get_concept(record.canonical_id)

    def list_active(self) -> list[CanonicalConcept]:
        """Active + Pending concepts (excluding STALE / TOMBSTONED)."""
        concepts = self.load_concepts()
        return [
            c for c in concepts.values()
            if c.status in {ReconciliationStatus.ACTIVE, ReconciliationStatus.PENDING}
        ]

    # ---- Write ------------------------------------------------------------

    def apply_decisions(
        self,
        new_page_id: str,
        decisions: list[ReconciliationDecisionRecord],
        *,
        language: str = "",
        resolver_fingerprint: str = "",
    ) -> list[CanonicalConcept]:
        """Apply a batch of decisions for one new page.

        Steps:
          1. sort decisions by priority asc (same > alias > ... > unresolved)
          2. for each decision:
             - DISTINCT  → new CanonicalConcept (script-owned id)
             - UNRESOLVED → skip (fail-closed; nothing to apply)
             - SAME / ALIAS / etc. with known ``candidate_canonical_id``
               → add ``new_page_id`` as member, update
               ``resolver_fingerprint``, bump ``version``
             - SAME / ALIAS / etc. with unknown canonical_id → log + skip
          3. atomic write of canonical_concepts.json
          4. append every decision to decision_log.jsonl

        Returns the list of canonical concepts touched.
        """
        concepts = self.load_concepts()
        aliases = self.load_aliases()
        touched: list[CanonicalConcept] = []
        effective_fp = resolver_fingerprint or self._fingerprint
        now_ms = int(time.time() * 1000)

        for decision in sort_decisions(decisions):
            # Always append to the decision log — audit is unconditional.
            self._append_decision_log(decision)

            verdict = decision.decision
            if verdict is ReconciliationDecision.UNRESOLVED:
                continue
            if verdict is ReconciliationDecision.DISTINCT:
                cid = new_canonical_id()
                preferred_label = new_page_id  # best default; resolver can amend later
                cc = CanonicalConcept(
                    canonical_id=cid,
                    preferred_label=preferred_label,
                    member_page_ids=[new_page_id],
                    status=ReconciliationStatus.ACTIVE,
                    resolver_fingerprint=effective_fp,
                    version=1,
                    created_at_ms=now_ms,
                    updated_at_ms=now_ms,
                )
                concepts[cid] = cc
                touched.append(cc)
                continue

            # SAME / ALIAS / BROADER / NARROWER / OVERLAP / CONFLICT
            cid_ref = decision.candidate_canonical_id
            if not cid_ref:
                _LOG.warning(
                    "apply_decisions: %s decision missing candidate_canonical_id (page=%s)",
                    verdict.value,
                    new_page_id,
                )
                continue
            cc = concepts.get(cid_ref)
            if cc is None:
                _LOG.warning(
                    "apply_decisions: unknown canonical_id %s for decision %s",
                    cid_ref,
                    verdict.value,
                )
                continue
            cc.add_member(new_page_id)
            cc.resolver_fingerprint = effective_fp
            cc.status = ReconciliationStatus.ACTIVE
            cc.version += 1
            cc.updated_at_ms = now_ms
            touched.append(cc)

        # Atomic write of the touched stores.
        self._save_concepts(concepts)
        if aliases is not None:
            self._save_aliases(aliases)
        return touched

    def remove_membership(self, page_id: str, canonical_id: str) -> bool:
        """Remove ``page_id`` from ``canonical_id``'s membership.

        Returns ``True`` iff ``page_id`` was a member (idempotent —
        removing a non-member returns ``False``).

        Reversibility
        -------------
        The canonical concept itself and its aliases are preserved. If
        the canonical ends up with zero members, its status transitions
        to ``TOMBSTONED`` but the record stays on disk so a later
        :py:meth:`apply_decisions` call (with the same page) can
        revive it via SAME.
        """
        concepts = self.load_concepts()
        cc = concepts.get(canonical_id)
        if cc is None:
            return False
        removed = cc.remove_member(page_id)
        if not removed:
            return False
        if not cc.member_page_ids:
            cc.status = ReconciliationStatus.TOMBSTONED
            cc.updated_at_ms = int(time.time() * 1000)
        self._save_concepts(concepts)
        return True

    # ---- F4: Fingerprint drift --------------------------------------------

    def mark_stale_concepts(self, current_fingerprint: str) -> list[str]:
        """Walk ACTIVE concepts and mark STALE on fingerprint drift.

        Returns the list of ``canonical_id`` values newly transitioned
        to ``STALE``. Concepts that already had status ``STALE`` (or
        ``TOMBSTONED`` / ``PENDING``) are left alone.
        """
        concepts = self.load_concepts()
        newly: list[str] = []
        for cid, cc in concepts.items():
            if cc.status is not ReconciliationStatus.ACTIVE:
                continue
            if cc.resolver_fingerprint == current_fingerprint:
                continue
            cc.status = ReconciliationStatus.STALE
            cc.updated_at_ms = int(time.time() * 1000)
            newly.append(cid)
        if newly:
            self._save_concepts(concepts)
        return newly

    # ---- F15: Alias single-source-of-truth -------------------------------

    def add_alias(
        self,
        alias_text: str,
        canonical_id: str,
        *,
        language: str = "",
        provenance: str = "resolver",
        resolver_fingerprint: str = "",
    ) -> AliasRecord:
        """Register an alias (F15 single source of truth).

        Idempotent
        ----------
        If ``(alias_text, language)`` already exists and points at
        ``canonical_id``, the existing record is returned unchanged.
        If it points at a *different* canonical_id, the first
        canonical_id wins (F15 acceptance: "同 alias 不同 canonical →
        保留第一个") — the second registration is silently ignored.

        The :py:class:`SlugAliasRegistryAdapter` is called for every
        call so ``.llm-wiki/slug_aliases.json`` stays in sync; the
        adapter itself swallows errors (best-effort).
        """
        aliases = self.load_aliases()
        key = (alias_text, language)
        existing = aliases.get(key)
        if existing is not None and existing.canonical_id != canonical_id:
            # Keep-first semantics. Still forward to the slug registry
            # so it sees the canonical (alias_text, language) binding
            # established first.
            self._adapter.register_alias(existing)
            return existing
        if existing is not None:
            # Already registered to the same canonical — return as-is.
            self._adapter.register_alias(existing)
            return existing

        record = AliasRecord(
            alias_text=alias_text,
            canonical_id=canonical_id,
            language=language,
            provenance=provenance,
            resolver_fingerprint=resolver_fingerprint,
            created_at_ms=int(time.time() * 1000),
        )
        aliases[key] = record
        self._save_aliases(aliases)
        self._adapter.register_alias(record)
        return record

    # ---- Internal helpers (used by tests + apply_decisions) --------------

    def _save_concepts(self, concepts: dict[str, CanonicalConcept]) -> None:
        """Atomically write the canonical concept map.

        Public-ish (single underscore): tests use it to seed fixtures
        without going through :py:meth:`apply_decisions`. The atomic
        write + JSON round-trip is the same path production uses.
        """
        payload = {cid: _concept_to_dict(cc) for cid, cc in concepts.items()}
        _atomic_write_json(canonical_concepts_path(self.root), payload)

    def _save_aliases(self, aliases: dict[tuple[str, str], AliasRecord]) -> None:
        """Atomically write the alias record map."""
        payload = {
            _pack_alias_key(k[0], k[1]): _alias_to_dict(v)
            for k, v in aliases.items()
        }
        _atomic_write_json(alias_records_path(self.root), payload)

    def _append_decision_log(self, decision: ReconciliationDecisionRecord) -> None:
        """Append a single decision to ``decision_log.jsonl``.

        Failure Contract §1: never raises. The audit log is best-effort
        — losing a log entry must not block canonical concept updates.
        """
        path = decision_log_path(self.root)
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


def _concept_to_dict(cc: CanonicalConcept) -> dict[str, Any]:
    return {
        "canonical_id": cc.canonical_id,
        "preferred_label": cc.preferred_label,
        "aliases": list(cc.aliases),
        "member_page_ids": list(cc.member_page_ids),
        "status": cc.status.value,
        "resolver_fingerprint": cc.resolver_fingerprint,
        "version": cc.version,
        "claim_ids": list(cc.claim_ids),
        "relation_ids": list(cc.relation_ids),
        "created_at_ms": cc.created_at_ms,
        "updated_at_ms": cc.updated_at_ms,
    }


def _concept_from_dict(raw: dict[str, Any]) -> CanonicalConcept:
    return CanonicalConcept(
        canonical_id=str(raw.get("canonical_id", "")),
        preferred_label=str(raw.get("preferred_label", "")),
        aliases=list(raw.get("aliases", []) or []),
        member_page_ids=list(raw.get("member_page_ids", []) or []),
        status=ReconciliationStatus(str(raw.get("status", "pending"))),
        resolver_fingerprint=str(raw.get("resolver_fingerprint", "")),
        version=int(raw.get("version", 1) or 1),
        claim_ids=list(raw.get("claim_ids", []) or []),
        relation_ids=list(raw.get("relation_ids", []) or []),
        created_at_ms=int(raw.get("created_at_ms", 0) or 0),
        updated_at_ms=int(raw.get("updated_at_ms", 0) or 0),
    )


def _alias_to_dict(record: AliasRecord) -> dict[str, Any]:
    return {
        "alias_text": record.alias_text,
        "canonical_id": record.canonical_id,
        "language": record.language,
        "provenance": record.provenance,
        "resolver_fingerprint": record.resolver_fingerprint,
        "created_at_ms": record.created_at_ms,
    }


def _pack_alias_key(alias_text: str, language: str) -> str:
    """Compact JSON-encodable key for the alias map.

    Using a single string (rather than a tuple key) makes JSON
    round-tripping trivial. The separator ``"\u0000"`` never appears
    in real alias text or language codes.
    """
    return f"{alias_text}\u0000{language}"


def _unpack_alias_key(key: str) -> tuple[str, str]:
    sep = "\u0000"
    if sep in key:
        alias_text, language = key.split(sep, 1)
        return alias_text, language
    return key, ""


def _decision_to_dict(decision: ReconciliationDecisionRecord) -> dict[str, Any]:
    return {
        "decision_id": decision.decision_id,
        "candidate_page_id": decision.candidate_page_id,
        "candidate_canonical_id": decision.candidate_canonical_id,
        "decision": decision.decision.value,
        "confidence": decision.confidence,
        "reason": decision.reason,
        "evidence_refs": list(decision.evidence_refs),
        "resolver_fingerprint": decision.resolver_fingerprint,
        "created_at_ms": decision.created_at_ms,
    }


__all__ = [
    "CanonicalRegistry",
    "reconciliation_dir",
    "canonical_concepts_path",
    "alias_records_path",
    "decision_log_path",
    "sort_decisions",
]
