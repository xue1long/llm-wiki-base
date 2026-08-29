"""Book view subsystem (A8 — 简化 Book 视图, spec §12.5).

Surface — four dataclasses + id generation policy + KU → Chapter mapper
+ Evidence Binder + KnowledgeCoreView:

    Book                       — top-level container (id, title, template_id,
                                 outline_version, publication_version,
                                 chapter_ids)
    Chapter                    — ordered slice of a Book (stable_key anchors
                                 OutlineProposal migrations)
    KnowledgeBlock             — content atom (6 block_types, StatementRef
                                 list, observed/synthesized knowledge_mode)
    OutlineProposal            — outline-change proposal with migration +
                                 rollback mappings; lifecycle vocabulary:
                                 proposed | approved | rejected | applied
    BookChapterRegistry        — immutable view of a Book's chapters with
                                 lookup helpers (B-T2)
    MappingDecision            — KU → Chapter mapper result (B-T2)
    MappingHint                — optional steer for the mapper (B-T2)
    derive_stable_key          — canonical stable_key derivation (B-T2)
    map_ku_to_chapter          — primary KU → Chapter mapper entry (B-T2)
    EvidenceRef                — block → evidence binding snapshot (B-T3a)
    bind_evidence              — resolve block.evidence_refs (B-T3a)
    KnowledgeCoreView          — read-only view of the Knowledge Core (B-T3a)
    SimpleKnowledgeCoreView    — in-memory default KnowledgeCoreView (B-T3a)

No compiler, no outline engine, no Markdown renderer — those land in B-T3b
and B-T4.
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
from .binder import (
    EvidenceRef,
    EvidenceRefStrength,
    EvidenceRefType,
    bind_evidence,
)
from .compiler import (
    ChapterRender,
    CompileError,
    CompiledBlock,
    compile_chapter,
    map_unit_type_to_block_type,
)
from .core_view import (
    KnowledgeCoreView,
    SimpleKnowledgeCoreView,
)
from .template import BookTemplate, BookView, compute_book_rendered_hash
from .markdown import render_chapter, render_chapter_from_dict
from .diff import BookDiff, affected_chapters, compute_book_diff
from .outline import (
    approve_outline_proposal,
    apply_outline_proposal,
    create_outline_proposal,
)

__all__ = [
    "Book",
    "BookChapterRegistry",
    "Chapter",
    "ChapterRender",
    "CompileError",
    "CompiledBlock",
    "EvidenceRef",
    "EvidenceRefStrength",
    "EvidenceRefType",
    "KnowledgeBlock",
    "KnowledgeBlockType",
    "KnowledgeCoreView",
    "KnowledgeMode",
    "MappingDecision",
    "MappingHint",
    "OutlineProposal",
    "OutlineProposalStatus",
    "SimpleKnowledgeCoreView",
    "StatementRef",
    "bind_evidence",
    "compile_chapter",
    "derive_stable_key",
    "generate_book_id",
    "generate_chapter_id",
    "generate_knowledge_block_id",
    "generate_outline_proposal_id",
    "map_ku_to_chapter",
    "map_unit_type_to_block_type",
    "BookTemplate",
    "BookView",
    "BookDiff",
    "affected_chapters",
    "approve_outline_proposal",
    "apply_outline_proposal",
    "compute_book_diff",
    "compute_book_rendered_hash",
    "create_outline_proposal",
    "render_chapter",
    "render_chapter_from_dict",
]
