"""Book view subsystem (A8 — 简化 Book 视图, spec §12.5).

B-T1 surface only — the four dataclasses plus id generation policy:

    Book                  — top-level container (id, title, template_id,
                            outline_version, publication_version, chapter_ids)
    Chapter               — ordered slice of a Book (stable_key anchors
                            OutlineProposal migrations)
    KnowledgeBlock        — content atom (6 block_types, StatementRef list,
                            observed/synthesized knowledge_mode)
    OutlineProposal       — outline-change proposal with migration +
                            rollback mappings; lifecycle vocabulary:
                            proposed | approved | rejected | applied

No compiler, no mapper, no outline engine, no Markdown renderer — those
land in B-T2 onwards.
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

__all__ = [
    "Book",
    "Chapter",
    "KnowledgeBlock",
    "KnowledgeBlockType",
    "KnowledgeMode",
    "OutlineProposal",
    "OutlineProposalStatus",
    "StatementRef",
    "generate_book_id",
    "generate_chapter_id",
    "generate_knowledge_block_id",
    "generate_outline_proposal_id",
]
