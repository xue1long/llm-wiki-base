"""Book view contract — Book / Chapter / KnowledgeBlock / OutlineProposal (B-T1).

Roadmap §12.5 (Book Contract) — A8 (简化 Book 视图):

    book:
      id, title, template_id, outline_version, publication_version, chapter_ids

    chapter:
      id, book_id, stable_key, title, order,
      knowledge_block_ids, source_knowledge_unit_ids, publication_version

    knowledge_block:
      id, chapter_id,
      block_type: definition | principle | method | example | perspective | conflict
      knowledge_unit_ids, statement_refs,
      evidence_refs, knowledge_mode: observed | synthesized

    outline_proposal:
      id, book_id, trigger_knowledge_unit_ids, affected_chapter_ids,
      migration_mapping, rollback_mapping,
      status: proposed | approved | rejected | applied
      reviewer

Plus the inner ``StatementRef`` (object_type + object_id).

This module is the B-T1 dataclass layer only:
* frozen dataclasses + Enum values
* ``to_dict()`` / ``from_dict()`` round-trip serialization
* ``from_dict()`` REJECTS unknown enum values with ``ValueError``

No behavior beyond dataclass + serialization. The compiler, mapper, outline
engine and Markdown renderer land in later B-T2+ tasks.

Default-value notes (B-T1 spec clarification):
    Book.outline_version = 1                  (int default)
    Book.publication_version = 0              (int default)
    KnowledgeBlock.knowledge_mode = "observed" (bare string default —
        matches the example YAML in spec §12.5; the field is validated as a
        2-value vocabulary on ``from_dict`` but stored as a plain string)
    OutlineProposal.status = "proposed"        (bare string default for
        symmetry with ``knowledge_mode``; validated as a 4-value vocabulary
        on ``from_dict``)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ─── Enums ──────────────────────────────────────────────────────────────


class KnowledgeBlockType(str, Enum):
    """Block type vocabulary (spec §12.5, 6 values)."""

    DEFINITION = "definition"
    PRINCIPLE = "principle"
    METHOD = "method"
    EXAMPLE = "example"
    PERSPECTIVE = "perspective"
    CONFLICT = "conflict"


class OutlineProposalStatus(str, Enum):
    """Outline proposal lifecycle (spec §12.5, 4 values)."""

    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"


# Allowed vocabulary for the string-defaulted fields (validation only).
# These are NOT dataclass field defaults — they are used by ``from_dict``.
_ALLOWED_KNOWLEDGE_MODES: frozenset[str] = frozenset({"observed", "synthesized"})
_ALLOWED_PROPOSAL_STATUSES: frozenset[str] = frozenset(
    {s.value for s in OutlineProposalStatus}
)
_ALLOWED_STATEMENT_OBJECT_TYPES: frozenset[str] = frozenset(
    {"claim", "structured_fact"}
)


# ─── Inner value object ─────────────────────────────────────────────────


@dataclass(frozen=True)
class StatementRef:
    """A reference from a KnowledgeBlock to a Claim or StructuredFact.

    spec §12.5: ``{object_type: claim | structured_fact, object_id: string}``
    """

    object_type: str  # "claim" | "structured_fact"
    object_id: str

    def to_dict(self) -> dict[str, str]:
        return {"object_type": self.object_type, "object_id": self.object_id}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "StatementRef":
        try:
            obj_type = payload["object_type"]
            obj_id = payload["object_id"]
        except KeyError as exc:  # surface field name explicitly
            raise ValueError(
                f"StatementRef.from_dict: missing required field '{exc.args[0]}'"
            ) from exc
        if obj_type not in _ALLOWED_STATEMENT_OBJECT_TYPES:
            raise ValueError(
                f"StatementRef.object_type: rejected value '{obj_type}' "
                f"(allowed: {sorted(_ALLOWED_STATEMENT_OBJECT_TYPES)})"
            )
        return cls(object_type=obj_type, object_id=obj_id)


# ─── Book ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Book:
    """spec §12.5 Book schema.

    Fields:
        id                    Book identifier (``book_<uuid8>_<slug>``).
        title                 Display title.
        template_id           Template reference (B-T2+ will resolve).
        outline_version       Increments on each approved outline change.
        publication_version   Increments on each recompile.
        chapter_ids           Ordered list of chapter ids.
    """

    id: str
    title: str
    template_id: str
    outline_version: int = 1
    publication_version: int = 0
    chapter_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "template_id": self.template_id,
            "outline_version": self.outline_version,
            "publication_version": self.publication_version,
            "chapter_ids": list(self.chapter_ids),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Book":
        return cls(
            id=payload["id"],
            title=payload["title"],
            template_id=payload["template_id"],
            outline_version=payload.get("outline_version", 1),
            publication_version=payload.get("publication_version", 0),
            chapter_ids=list(payload.get("chapter_ids", [])),
        )


# ─── Chapter ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Chapter:
    """spec §12.5 Chapter schema.

    Fields:
        id                         Chapter identifier (``ch_<uuid8>_<slug>``).
        book_id                    Parent Book id.
        stable_key                 Stable across outline changes (used by
                                   OutlineProposal migration_mapping).
        title                      Display title.
        order                      Position within the Book.
        knowledge_block_ids        Ordered list of block ids in this chapter.
        source_knowledge_unit_ids   Source KU ids feeding the chapter.
        publication_version        Increments on each recompile.
    """

    id: str
    book_id: str
    stable_key: str
    title: str
    order: int
    knowledge_block_ids: list[str] = field(default_factory=list)
    source_knowledge_unit_ids: list[str] = field(default_factory=list)
    publication_version: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "book_id": self.book_id,
            "stable_key": self.stable_key,
            "title": self.title,
            "order": self.order,
            "knowledge_block_ids": list(self.knowledge_block_ids),
            "source_knowledge_unit_ids": list(self.source_knowledge_unit_ids),
            "publication_version": self.publication_version,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Chapter":
        return cls(
            id=payload["id"],
            book_id=payload["book_id"],
            stable_key=payload["stable_key"],
            title=payload["title"],
            order=payload["order"],
            knowledge_block_ids=list(payload.get("knowledge_block_ids", [])),
            source_knowledge_unit_ids=list(
                payload.get("source_knowledge_unit_ids", [])
            ),
            publication_version=payload.get("publication_version", 0),
        )


# ─── KnowledgeBlock ────────────────────────────────────────────────────


@dataclass(frozen=True)
class KnowledgeBlock:
    """spec §12.5 KnowledgeBlock schema.

    Fields:
        id                  Block identifier (``kb_<uuid8>_<slug>``).
        chapter_id          Parent Chapter id.
        block_type          One of the 6 KnowledgeBlockType values.
        knowledge_unit_ids  Source KU ids feeding this block.
        statement_refs      List[StatementRef] — claims / structured facts
                            backing the block.
        evidence_refs       Evidence ids supporting the statements.
        knowledge_mode      ``"observed"`` | ``"synthesized"`` (string default
                            — see module docstring).
    """

    id: str
    chapter_id: str
    block_type: KnowledgeBlockType
    knowledge_unit_ids: list[str] = field(default_factory=list)
    statement_refs: list[StatementRef] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    knowledge_mode: str = "observed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "chapter_id": self.chapter_id,
            "block_type": self.block_type.value,
            "knowledge_unit_ids": list(self.knowledge_unit_ids),
            "statement_refs": [ref.to_dict() for ref in self.statement_refs],
            "evidence_refs": list(self.evidence_refs),
            "knowledge_mode": self.knowledge_mode,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "KnowledgeBlock":
        # block_type — must be a known KnowledgeBlockType value
        raw_type = payload.get("block_type")
        try:
            block_type = KnowledgeBlockType(raw_type)
        except ValueError as exc:
            allowed = sorted(t.value for t in KnowledgeBlockType)
            raise ValueError(
                f"KnowledgeBlock.block_type: rejected value '{raw_type}' "
                f"(allowed: {allowed})"
            ) from exc

        # knowledge_mode — must be one of the 2-value vocabulary
        raw_mode = payload.get("knowledge_mode", "observed")
        if raw_mode not in _ALLOWED_KNOWLEDGE_MODES:
            raise ValueError(
                f"KnowledgeBlock.knowledge_mode: rejected value '{raw_mode}' "
                f"(allowed: {sorted(_ALLOWED_KNOWLEDGE_MODES)})"
            )

        # statement_refs — nested dataclasses
        raw_refs = payload.get("statement_refs", [])
        if not isinstance(raw_refs, list):
            raise ValueError(
                "KnowledgeBlock.statement_refs: expected list, got "
                f"{type(raw_refs).__name__}"
            )
        refs = [StatementRef.from_dict(r) for r in raw_refs]

        return cls(
            id=payload["id"],
            chapter_id=payload["chapter_id"],
            block_type=block_type,
            knowledge_unit_ids=list(payload.get("knowledge_unit_ids", [])),
            statement_refs=refs,
            evidence_refs=list(payload.get("evidence_refs", [])),
            knowledge_mode=raw_mode,
        )


# Backwards-compat alias kept for downstream callers that already
# reference ``KnowledgeMode`` from earlier plans. ``knowledge_mode`` is
# stored as a plain string per spec §12.5; this is the matching
# vocabulary the dataclass validates against.
KnowledgeMode = _ALLOWED_KNOWLEDGE_MODES  # type: ignore[assignment]


# ─── OutlineProposal ───────────────────────────────────────────────────


@dataclass(frozen=True)
class OutlineProposal:
    """spec §12.5 OutlineProposal schema.

    Fields:
        id                          Proposal identifier (``op_<uuid8>_<slug>``).
        book_id                     Target Book id.
        trigger_knowledge_unit_ids  KUs that triggered this proposal.
        affected_chapter_ids        Chapters the proposal would touch.
        migration_mapping           stable_key -> new chapter id (forward).
        rollback_mapping            new chapter id -> original stable_key (back).
        status                      Lifecycle state (validated vocabulary).
        reviewer                    Reviewer identifier (None = pending).

    Until ``status == "approved"``, the Book's ``outline_version`` must NOT
    change (spec §12.5 last paragraph). The enforcement of that rule lives
    in B-T2+; this dataclass only stores the data.
    """

    id: str
    book_id: str
    trigger_knowledge_unit_ids: list[str] = field(default_factory=list)
    affected_chapter_ids: list[str] = field(default_factory=list)
    migration_mapping: dict[str, Any] = field(default_factory=dict)
    rollback_mapping: dict[str, Any] = field(default_factory=dict)
    status: str = "proposed"
    reviewer: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "book_id": self.book_id,
            "trigger_knowledge_unit_ids": list(self.trigger_knowledge_unit_ids),
            "affected_chapter_ids": list(self.affected_chapter_ids),
            "migration_mapping": dict(self.migration_mapping),
            "rollback_mapping": dict(self.rollback_mapping),
            "status": self.status,
            "reviewer": self.reviewer,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "OutlineProposal":
        raw_status = payload.get("status", "proposed")
        if raw_status not in _ALLOWED_PROPOSAL_STATUSES:
            raise ValueError(
                f"OutlineProposal.status: rejected value '{raw_status}' "
                f"(allowed: {sorted(_ALLOWED_PROPOSAL_STATUSES)})"
            )
        return cls(
            id=payload["id"],
            book_id=payload["book_id"],
            trigger_knowledge_unit_ids=list(
                payload.get("trigger_knowledge_unit_ids", [])
            ),
            affected_chapter_ids=list(payload.get("affected_chapter_ids", [])),
            migration_mapping=dict(payload.get("migration_mapping", {})),
            rollback_mapping=dict(payload.get("rollback_mapping", {})),
            status=raw_status,
            reviewer=payload.get("reviewer"),
        )
