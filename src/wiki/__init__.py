"""Public wiki API facade.

The implementation is split into three layers:

* :mod:`src.wiki.core` contains the data model, types, paths, and ID helpers.
* :mod:`src.wiki.storage` contains filesystem read/write primitives.
* :mod:`src.wiki.features` contains business-level wiki operations.

Importers should use the layered sub-package paths directly
(e.g. ``src.wiki.core.types``, ``src.wiki.storage.page_writer``,
``src.wiki.features.relations``). The facade re-exports below preserve
``from src.wiki import X`` for the most commonly used symbols.
"""

from __future__ import annotations

from .core.id_generator import ID_PATTERN, generate_page_id, is_valid_id
from .core.page_model import WikiPage
from .core.paths import WikiPaths
from .core.types import (
    PageType,
    ReviewItem,
    make_review_item,
)
from .features.relations import (
    INVERSE_RELATIONS,
    SYMMETRIC_RELATIONS,
    USER_TYPE_PREFIX,
    Relation,
    RelationQuery,
    RelationSync,
    RelationType,
    SyncReport,
    parse_relations_from_response,
)
from .features.slug_aliases import SlugAliasRegistry
from .storage.atomic_ctx_helpers import atomic_pipeline_op
from .storage.ensure import ensure_knowledge_base
from .storage.page_writer import (
    PageNotFoundError,
    page_path_for,
    page_path_for_stub,
    read_page,
    write_page,
)

__all__ = [
    # Core data and paths
    "PageType",
    "WikiPage",
    "ReviewItem",
    "make_review_item",
    "WikiPaths",
    "generate_page_id",
    "is_valid_id",
    "ID_PATTERN",
    # Storage
    "PageNotFoundError",
    "write_page",
    "read_page",
    "page_path_for",
    "page_path_for_stub",
    "ensure_knowledge_base",
    "atomic_pipeline_op",
    # Relations (historically available through the relations module and
    # useful as direct facade imports)
    "Relation",
    "RelationType",
    "RelationSync",
    "RelationQuery",
    "SyncReport",
    "parse_relations_from_response",
    "INVERSE_RELATIONS",
    "SYMMETRIC_RELATIONS",
    "USER_TYPE_PREFIX",
    "SlugAliasRegistry",
]
