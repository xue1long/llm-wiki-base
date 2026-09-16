"""Task 27 — Reconciliation canonical models + Decision enum.

This module is the *vocabulary* of the reconciliation subsystem
(Tasks 27-32 of the v7 stage remediation plan). It defines:

  * ``ReconciliationDecision`` — the 8-way verdict an LLM resolver can
    emit (Task 29 will feed this enum into the LLM prompt).
  * ``ReconciliationStatus`` — the lifecycle state of a
    ``CanonicalConcept`` (mirrors Stage 6R's RelationRunStatus but
    adapted for canonical concepts).
  * ``CanonicalConcept`` — the aggregate that owns a set of
    equivalent wiki pages.
  * ``AliasRecord`` — a single multilingual alias for a canonical
    concept.
  * ``ReconciliationDecisionRecord`` — a single verdict emitted by the
    LLM resolver, with provenance + idempotency id.
  * ``new_canonical_id`` / ``decision_id_for`` — the two
    script-owned id helpers (Identity Contract).
  * ``SlugAliasRegistryAdapter`` — interface declaration only; Task 30
    wires the real integration (F15).

Design notes
------------
The dataclasses are intentionally minimal: the reconciliation
subsystem is a *view* on top of the existing wiki pipeline (collector →
analyzer → reviewer → promoter → generator → writer), and the heavy
lifting (durable storage, prompt construction, decision application,
slug routing) lives in later tasks. Keeping this module thin lets us
ship the vocabulary first and iterate on the semantics.

Identity Contract
-----------------
Both ``canonical_id`` and ``decision_id`` are script-owned:

  * ``new_canonical_id()``        — uuid4 hex[:16], prefixed ``c-``
  * ``decision_id_for(...)``      — sha1 of (page_id|canonical_id|decision)
                                    truncated to 12 hex chars, prefixed
                                    ``dec-``

The LLM resolver (Task 29) emits decisions but **never** ids.
Receiving a LLM-produced canonical_id or decision_id is a hard
invariant violation that Task 29 will assert at the prompt boundary.

Failure Contract
----------------
``new_canonical_id`` and ``decision_id_for`` never raise; ``uuid4``
and ``sha1`` are total functions, so any exception here would be a
library bug. ``SlugAliasRegistryAdapter.register_alias`` swallows
exceptions from the upstream registry (F15 — alias registration is
best-effort; failure must not block canonical concept creation).
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------


class ReconciliationDecision(str, Enum):
    """Identity resolver verdict vocabulary (Task 29 feeds this to LLM).

    Priority for ``apply_decisions`` (Task 30 implements the ordering):

        same > alias > conflict > overlap > broader/narrower >
        distinct > unresolved

    String-valued so JSON / frontmatter round-trip cleanly.
    """

    SAME = "same"             # A and B refer to the same concept; merge memberships
    ALIAS = "alias"           # A is an alternative label for B
    BROADER = "broader"       # A is a hypernym of B (B ⊊ A)
    NARROWER = "narrower"     # A is a hyponym of B (A ⊊ B)
    OVERLAP = "overlap"       # A and B share some members but neither contains the other
    CONFLICT = "conflict"     # A and B refer to different concepts (mark for human review)
    DISTINCT = "distinct"     # A and B are different concepts (no relation)
    UNRESOLVED = "unresolved" # technical failure or insufficient evidence


# Module-level invariant — the enum is the contract.
assert len(ReconciliationDecision) == 8, (
    "ReconciliationDecision must have exactly 8 members; "
    "do not silently add or remove values."
)


class ReconciliationStatus(str, Enum):
    """Lifecycle status for a CanonicalConcept.

    Mirrors Stage 6R's ``RelationRunStatus``
    (PENDING / READY / PARTIAL / FAILED / STALE) but adapted for the
    canonical concept lifecycle. Notably we drop READY/PARTIAL/FAILED
    (those describe a run, not a concept) and add TOMBSTONED for the
    case where the last member has been removed.
    """

    PENDING = "pending"           # just created, no decisions yet
    ACTIVE = "active"             # at least one decision applied; resolvable
    STALE = "stale"               # resolver_fingerprint drift (F4)
    TOMBSTONED = "tombstoned"     # last member removed


# ---------------------------------------------------------------------------
# Canonical concept aggregate
# ---------------------------------------------------------------------------


@dataclass
class CanonicalConcept:
    """A canonical concept groups wiki pages that refer to the same thing.

    Identity Contract
    -----------------
    ``canonical_id`` is script-owned (``new_canonical_id()``). The LLM
    resolver (Task 29) never produces or fabricates this id; it only
    *refers* to canonical ids when emitting a decision.

    F4 — resolver_fingerprint
    -------------------------
    A drift in ``resolver_fingerprint`` (the LLM that last updated this
    canonical concept) signals that the decision may need re-running
    under the new resolver. Task 30 wires the fingerprint to the
    resolver config hash and bumps the concept to ``STALE`` on drift.

    Mutation discipline
    -------------------
    ``add_member`` and ``remove_member`` are the only sanctioned ways
    to mutate ``member_page_ids``. Direct assignment is fine but
    callers should bump ``version`` and ``updated_at_ms`` — Task 30's
    ``apply_decisions`` is the canonical mutator.
    """

    canonical_id: str                    # c-<uuid4_hex[:16]>; script-owned, never LLM-derived
    preferred_label: str                 # human-readable label; can change without ID change
    aliases: list[str] = field(default_factory=list)  # alternative labels (multilingual OK)
    member_page_ids: list[str] = field(default_factory=list)  # wiki page_ids that belong to this canonical
    status: ReconciliationStatus = ReconciliationStatus.PENDING
    resolver_fingerprint: str = ""       # F4: fingerprint of resolver that created/updated this
    version: int = 1                     # bump on every apply_decisions mutation
    claim_ids: list[str] = field(default_factory=list)
    relation_ids: list[str] = field(default_factory=list)
    created_at_ms: int = 0
    updated_at_ms: int = 0

    def add_member(self, page_id: str) -> None:
        """Idempotent: add ``page_id`` if not already present.

        Failure Contract: never raises. An empty/whitespace ``page_id``
        is ignored (it would never be a valid wiki page id, and adding
        it would just clutter ``member_page_ids``).
        """
        if not page_id:
            return
        if page_id not in self.member_page_ids:
            self.member_page_ids.append(page_id)

    def remove_member(self, page_id: str) -> bool:
        """Remove ``page_id`` if present. Returns ``True`` iff removed.

        Failure Contract: never raises. When the last member is
        removed the caller is responsible for transitioning ``status``
        to ``TOMBSTONED`` (the dataclass doesn't do it automatically —
        we want that decision to be auditable, not implicit).
        """
        try:
            self.member_page_ids.remove(page_id)
        except ValueError:
            return False
        return True


# ---------------------------------------------------------------------------
# Alias records
# ---------------------------------------------------------------------------


@dataclass
class AliasRecord:
    """A single alternative label for a canonical concept.

    Multilingual support
    --------------------
    ``language`` is ISO 639-1 (e.g. ``"en"``, ``"zh"``, ``"ja"``) or
    ``""`` for language-agnostic labels. Several records may share a
    ``canonical_id`` across different languages — that's how a single
    canonical concept supports multilingual aliases (e.g. "RAG" / en
    + "检索增强生成" / zh + "検索拡張生成" / ja).

    Provenance
    ----------
    ``provenance`` is a short free-form tag describing *where* the
    alias came from — useful when the alias needs to be reviewed
    (``"manual"``, ``"resolver:fp-1"``, ``"alias_dict"``,
    ``"llm_suggested"``, ...). It is not a strict enum; future
    provenance sources shouldn't require a code change.
    """

    alias_text: str            # e.g. "RAG", "检索增强生成", "Retrieval-Augmented Generation"
    canonical_id: str          # link to CanonicalConcept
    language: str              # ISO 639-1 (e.g. "en", "zh", "ja") or "" for language-agnostic
    provenance: str = ""       # e.g. "manual", "resolver:fp-1", "alias_dict"
    resolver_fingerprint: str = ""
    created_at_ms: int = 0


# ---------------------------------------------------------------------------
# Decision records
# ---------------------------------------------------------------------------


@dataclass
class ReconciliationDecisionRecord:
    """A single verdict emitted by the LLM resolver.

    Identity Contract
    -----------------
    ``decision_id`` is script-owned (``decision_id_for``); the LLM
    never produces it. ``candidate_canonical_id`` may be ``None`` when
    the decision is ``DISTINCT`` (no canonical concept exists yet) or
    ``UNRESOLVED`` (insufficient evidence to pick one). For all other
    decisions it must be set.

    Evidence references
    -------------------
    ``evidence_refs`` is a free-form list (typ. claim ids or page
    ids) the LLM used to justify its verdict. The dataclass doesn't
    validate the type — Task 29 will constrain it from the LLM
    structured-output schema.
    """

    decision_id: str                       # script-owned (sha1)
    candidate_page_id: str                 # the new page being reconciled
    candidate_canonical_id: str | None     # None when decision is DISTINCT/UNRESOLVED
    decision: ReconciliationDecision
    confidence: float                      # 0..1
    reason: str = ""                       # short explanation (<=200 chars)
    evidence_refs: list[Any] = field(default_factory=list)
    resolver_fingerprint: str = ""
    created_at_ms: int = 0


# ---------------------------------------------------------------------------
# Script-owned id helpers (Identity Contract)
# ---------------------------------------------------------------------------


def new_canonical_id() -> str:
    """Return a fresh canonical id: ``c-<uuid4_hex[:16]>``.

    Failure Contract: never raises (``uuid.uuid4`` is total).
    """
    return "c-" + uuid.uuid4().hex[:16]


def decision_id_for(
    page_id: str,
    canonical_id: str | None,
    decision: ReconciliationDecision,
) -> str:
    """Return a deterministic decision id: ``dec-<sha1[:12]>``.

    Hashes ``"{page_id}|{canonical_id or ''}|{decision.value}"`` with
    sha1. Truncating to 12 hex chars (48 bits) is ample for collision
    avoidance *within a single resolver run*; cross-run uniqueness is
    not required because each run writes its own decision log.

    Failure Contract: never raises. Garbage inputs (``None`` for
    ``page_id``, ``""`` for ``canonical_id``) are coerced to strings
    so the helper stays total — the resulting id is still deterministic
    but obviously bad, which a downstream audit can flag.
    """
    payload = f"{page_id or ''}|{canonical_id or ''}|{decision.value}"
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]
    return "dec-" + digest


# ---------------------------------------------------------------------------
# F15 SlugAliasRegistry adapter — interface only
# ---------------------------------------------------------------------------


class SlugAliasRegistryAdapter:
    """F15 整改要求: alias 单一真源在 ``SlugAliasRegistry``.

    Reconciliation's ``AliasRecord`` is the *human-readable label view*;
    ``SlugAliasRegistry`` is the URL/slug router's view. This adapter
    bridges the two by registering the canonical alias with the slug
    registry when ``AliasRecord`` instances are applied.

    Task 27 only declares the interface; **Task 30 wires the actual
    integration** (deciding when to call ``register_alias``, how to
    merge conflicting slugs, etc.). The interface is intentionally
    small so Task 30's design can extend it without a breaking change.
    """

    def __init__(self, slug_registry: Any | None = None) -> None:
        self._slug_registry = slug_registry

    def register_alias(self, alias: AliasRecord) -> None:
        """Forward ``alias_text -> canonical_id`` to ``slug_registry``.

        Best-effort:

          * No-op when ``slug_registry`` is ``None`` (Task 27 unit tests
            don't need to wire a real registry).
          * Never raises — alias registration is a side concern of
            canonical concept creation, and failing it must not roll
            back the canonical update (Failure Contract §1).
        """
        if self._slug_registry is None:
            return
        try:
            register = getattr(self._slug_registry, "register", None)
            if callable(register):
                register(alias_text=alias.alias_text, canonical_id=alias.canonical_id)
        except Exception:
            # F15 — slug registration is best-effort. Swallow so the
            # canonical concept update path stays total.
            return