"""Public wiki API facade.

The implementation is split into three layers:

* :mod:`src.wiki.core` contains the data model, types, paths, and ID helpers.
* :mod:`src.wiki.storage` contains filesystem read/write primitives.
* :mod:`src.wiki.features` contains business-level wiki operations.

The compatibility aliases below deliberately keep every historical
``src.wiki.<module>`` import working while callers migrate to the layered
packages.  In particular, aliases are registered in ``sys.modules`` because
``from src.wiki.page_writer import ...`` resolves a submodule rather than a
package attribute.
"""

from __future__ import annotations

import importlib
import sys

from .core.id_generator import ID_PATTERN, generate_page_id, is_valid_id
from .core.page_model import WikiPage
from .core.paths import WikiPaths
from .core.types import (
    EventName,
    KnowledgeTask,
    PageType,
    ReviewItem,
    TaskStatus,
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
from .storage.atomic_ctx_helpers import atomic_pipeline_op
from .storage.ensure import ensure_knowledge_base
from .storage.page_writer import (
    PageNotFoundError,
    page_path_for,
    page_path_for_stub,
    read_page,
    write_page,
)

# Import feature modules once and expose them at the facade, preserving
# ``from src.wiki import relations`` and equivalent historical imports.
_LEGACY_MODULE_TARGETS = {
    "types": ".core.types",
    "page_model": ".core.page_model",
    "paths": ".core.paths",
    "id_generator": ".core.id_generator",
    "page_writer": ".storage.page_writer",
    "ensure": ".storage.ensure",
    "atomic_ctx_helpers": ".storage.atomic_ctx_helpers",
    "relations": ".features.relations",
    "heat": ".features.heat",
    "review": ".features.review",
    "lint": ".features.lint",
    "lint_cache": ".features.lint_cache",
    "dedup": ".features.dedup",
    "dedup_auto": ".features.dedup_auto",
    "stubs": ".features.stubs",
    "zombie": ".features.zombie",
    "tag_namespace": ".features.tag_namespace",
    "import_": ".features.import_",
    "export": ".features.export",
    "cascade_delete": ".features.cascade_delete",
    "indexer": ".features.indexer",
    "wikilink": ".features.wikilink",
    "folder_ingest": ".features.folder_ingest",
    "schema_routing": ".features.schema_routing",
    "logger": ".features.logger",
}

for _legacy_name, _target in _LEGACY_MODULE_TARGETS.items():
    _module = importlib.import_module(_target, __name__)
    globals()[_legacy_name] = _module
    sys.modules[f"{__name__}.{_legacy_name}"] = _module

__all__ = [
    # Core data and paths
    "PageType",
    "EventName",
    "TaskStatus",
    "WikiPage",
    "KnowledgeTask",
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
    # Compatibility module exports
    *_LEGACY_MODULE_TARGETS.keys(),
]

# Avoid leaking implementation helpers as public module state.
del _legacy_name, _target, _module
del importlib
del sys
del _LEGACY_MODULE_TARGETS
