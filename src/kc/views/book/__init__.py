"""Book view subsystem (A8 — 简化 Book 视图, spec §12.5).

Surface — four dataclasses + id generation policy + KU → Chapter mapper:

    Book                  — top-level container (id, title, template_id,
                            outline_version, publication_version, chapter_ids)
    Chapter               — ordered slice of a Book (stable_key anchors
                            OutlineProposal migrations)
    KnowledgeBlock        — content atom (6 block_types, StatementRef list,
                            observed/synthesized knowledge_mode)
    OutlineProposal       — outline-change proposal with migration +
                            rollback mappings; lifecycle vocabulary:
                            proposed | approved | rejected | applied
    BookChapterRegistry   — immutable view of a Book's chapters with
                            lookup helpers (B-T2)
    MappingDecision       — KU → Chapter mapper result (B-T2)
    MappingHint           — optional steer for the mapper (B-T2)
    derive_stable_key     — canonical stable_key derivation (B-T2)
    map_ku_to_chapter     — primary KU → Chapter mapper entry (B-T2)

No compiler, no binder, no outline engine, no Markdown renderer — those
land in B-T3 onwards.
"""
from .contract import (
    KnowledgeBlock,
    KnowledgeBlockType,
    KnowledgeMode,
    OutlineProposal,
    OutlineProposalStatus,
    StatementRef,
    Book,
    Chapter,
)
from .id_policy import (
    generate_book_id,
    generate_chapter_id,
    generate_knowledge_block_id,
    generate_outline_proposal_id,
)
from .mapper import (
    BookChapterRegistry,
    MappingDecision,
    MappingHint,
    derive_stable_key,
    map_ku_to_chapter,
)

__all__ = [
    "Book",
    "BookChapterRegistry",
    "Chapter",
    "KnowledgeBlock",
    "KnowledgeBlockType",
    "KnowledgeMode",
    "MappingDecision",
    "MappingHint",
    "OutlineProposal",
    "OutlineProposalStatus",
    "StatementRef",
    "derive_stable_key",
    "generate_book_id",
    "generate_chapter_id",
    "generate_knowledge_block_id",
    "generate_outline_proposal_id",
    "map_ku_to_chapter",
]
