# ruflo-kb/src/vector/store.py
"""Per-project LanceDB handle store.

There is one :class:`lancedb.LanceDB` (and a corresponding ``chunks`` table)
per project. ``init_vector_store_for_paths(paths)`` opens the handle for
``paths.root`` and stores it in a ``{path: (db, table)}`` map. ``get_table()``
returns the table for whichever project was most recently initialised
(``current_project_key``).

Dimension policy (plan Phase 4 guidance #9 / B11 / H13): the store schema is
no longer a hardcoded 384. ``init_vector_store_for_paths(paths, expected_dim)``
creates a table matching *expected_dim* (the embedding provider's output
dimension — local sentence-transformers 384, remote OpenAI/MiniMax 1536).
A dimension mismatch against an existing table raises
:class:`VectorDimensionMismatchError` instead of silently dropping the table
(which destroyed data). The ONLY legal drop path is the explicit
:func:`rebuild_vector_schema` (operator / rollback-batch decision point).

Note: the legacy ``init_vector_store(db_path: str)`` entry point (parent-walking
heuristic) has been removed. Callers must construct a ``WikiPaths`` explicitly
and pass it to ``init_vector_store_for_paths``.
"""
from pathlib import Path
from typing import Any, Optional

from ..utils.path import safe_resolve_str

from ..wiki.core.paths import WikiPaths

import lancedb
import pyarrow as pa

import logging
_logger = logging.getLogger(__name__)


# Default embedding dimension when no provider dimension is supplied
# (local sentence-transformers all-MiniLM-L6-v2).
DEFAULT_EMBEDDING_DIM = 384


class VectorDimensionMismatchError(RuntimeError):
    """Existing ``chunks`` table dimension differs from the expected one.

    Raised by :func:`init_vector_store_for_paths` on a mismatch. The table
    is left untouched — the caller (executor / operator) must decide:
    switch the embedding provider to match the store, or explicitly rebuild
    the store via :func:`rebuild_vector_schema`.
    """


# ---------------------------------------------------------------------------
# Per-project state
# ---------------------------------------------------------------------------
# ``_per_project`` maps ``safe_resolve_str(paths.root)`` -> ``(db, table)``.
# A second project init does not affect the first project's handle.
_per_project: dict[str, tuple[Any, Any]] = {}
# ``current_project_key`` is the active project for ``get_table()`` and is
# updated every time ``init_vector_store_for_paths`` is called.
_current_project_key: Optional[str] = None


def _build_schema(dim: int = DEFAULT_EMBEDDING_DIM):
    """Build the LanceDB schema with the given embedding dimension.

    Schema construction uses ``pyarrow`` attributes (``.string``, ``.list_``,
    ``.float32``, etc.). Building it lazily inside :func:`init_vector_store_for_paths`
    instead of at module-import time keeps the module importable even when
    ``pyarrow`` is stubbed out by the test conftest hierarchy.
    """
    return pa.schema([
        ("id", pa.string()),
        ("task_id", pa.string()),
        ("content", pa.string()),
        ("embedding", pa.list_(pa.float32(), dim)),
        ("path", pa.string()),
        ("updated_at", pa.int64()),
    ])


def _table_dim(table) -> Optional[int]:
    """Read the embedding dimension from a live table schema, or None."""
    try:
        ftype = table.schema.field("embedding").type
        return int(getattr(ftype, "list_size", 0)) or None
    except Exception:
        return None


def _project_key(paths: WikiPaths) -> str:
    """Stable identifier for a project root — safe from CJK corruption."""
    return safe_resolve_str(paths.root)


def init_vector_store_for_paths(paths: WikiPaths, expected_dim: int | None = None) -> None:
    """Open (or reuse) the LanceDB handle for ``paths.root``.

    * If a handle is already cached for this project, it is reused and
      ``_current_project_key`` is updated to point at it.
    * Otherwise the handle is opened freshly and added to ``_per_project``.

    *expected_dim* is the embedding provider's output dimension (384 local /
    1536 remote). When an existing ``chunks`` table has a different
    dimension, :class:`VectorDimensionMismatchError` is raised and the table
    is left untouched — no silent drop (B11 / H13). When *expected_dim* is
    ``None`` (read-only callers like ``get_table`` / ``delete_by_source``),
    the existing store dimension is adopted unchanged and no check runs.
    Use :func:`rebuild_vector_schema` for the explicit migration decision.

    LanceDB files are persisted at ``paths.index / "lancedb"``.
    """
    global _current_project_key
    key = _project_key(paths)

    if key in _per_project:
        # Cached handle — still honour an explicit dimension contract.
        if expected_dim is not None:
            _cached_table = _per_project[key][1]
            _cached_dim = _table_dim(_cached_table)
            if _cached_dim is not None and _cached_dim != expected_dim:
                raise VectorDimensionMismatchError(
                    f"existing 'chunks' table is {_cached_dim}-dim but the "
                    f"embedding provider produces {expected_dim}-dim — "
                    f"refusing to drop it silently. Decide explicitly: switch "
                    f"the provider to {_cached_dim}-dim, or rebuild the store "
                    f"via rebuild_vector_schema(paths, dim={expected_dim})."
                )
        _current_project_key = key
        return

    db_dir = paths.index / "lancedb"
    db_dir.mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(str(db_dir))

    existing = None
    try:
        existing = db.open_table("chunks")
    except Exception:
        existing = None

    if existing is not None:
        store_dim = _table_dim(existing)
        if expected_dim is not None and store_dim is not None and store_dim != expected_dim:
            raise VectorDimensionMismatchError(
                f"existing 'chunks' table is {store_dim}-dim but the "
                f"embedding provider produces {expected_dim}-dim — "
                f"refusing to drop it silently. Decide explicitly: switch "
                f"the provider to {store_dim}-dim, or rebuild the store "
                f"via rebuild_vector_schema(paths, dim={expected_dim})."
            )
        table = existing
    else:
        table = db.create_table(
            "chunks", schema=_build_schema(expected_dim or DEFAULT_EMBEDDING_DIM))

    _per_project[key] = (db, table)
    _current_project_key = key


def rebuild_vector_schema(paths: WikiPaths, dim: int = DEFAULT_EMBEDDING_DIM) -> int:
    """Explicitly drop and recreate the ``chunks`` table at ``dim``.

    This is the ONLY legal drop path (plan Phase 4 guidance #9 — 禁止静默
    drop，维度迁移是显式决策). Returns the previous dimension (0 if no
    table existed). Same-dimension calls are a no-op.

    Callers (rollback_batch.py, operator scripts) are expected to re-upsert
    vectors afterwards — dropping the table deletes its rows.
    """
    key = _project_key(paths)
    db_dir = paths.index / "lancedb"
    db_dir.mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(str(db_dir))
    old_dim = 0
    try:
        existing = db.open_table("chunks")
        old_dim = _table_dim(existing) or 0
    except Exception:
        existing = None

    if existing is not None:
        if old_dim == dim:
            _logger.info("[vector] rebuild_vector_schema: dim %d unchanged — no-op", dim)
        else:
            _logger.warning(
                "[vector] rebuild_vector_schema: dropping %d-dim table, recreating %d-dim (explicit decision)",
                old_dim, dim,
            )
            db.drop_table("chunks")
        db.create_table("chunks", schema=_build_schema(dim), exist_ok=True)
    else:
        db.create_table("chunks", schema=_build_schema(dim), exist_ok=True)

    # Refresh the cached handle so callers see the new table.
    if key in _per_project:
        del _per_project[key]
    _current_project_key = None
    return old_dim


def get_table(project_paths: "WikiPaths | None" = None):
    """Return the LanceDB table for the requested project.

    Audit I3: ``get_table()`` previously returned the table for whichever
    project was most recently initialised — so a search request for
    project B silently read project A's vectors. The fix is to accept an
    explicit ``project_paths`` argument so the search service resolves the
    correct handle. Falls back to the process-global "current" handle for
    legacy callers (single-project CLI, tests).

    Args:
        project_paths: optional WikiPaths for the target project. When
            provided, the table for THAT project is returned regardless of
            which project is currently "active".

    Raises:
        RuntimeError: when no project has been initialised yet (and no
            explicit paths were passed).
    """
    if project_paths is not None:
        key = _project_key(project_paths)
        if key not in _per_project:
            # Lazy initialisation so callers do not have to call
            # `init_vector_store_for_paths` separately. Opens the handle on
            # demand for this specific project.
            init_vector_store_for_paths(project_paths)
        _, table = _per_project[key]
        return table
    if _current_project_key is None:
        raise RuntimeError("Vector store not initialized")
    _, table = _per_project[_current_project_key]
    return table


def delete_by_source(paths: WikiPaths, raw_path: str) -> int:
    """Delete every vector whose ``path`` column matches ``raw_path``.

    Used by reingest: before re-running ingestion of a source, its old
    vectors must be removed so the search index does not serve stale
    chunks. Matches on the exact ``path`` value (project-relative, forward
    slashes) that the ingest pipeline stored at upsert time.

    Args:
        paths: WikiPaths for the target project.
        raw_path: project-relative raw path stored in the ``path`` column.

    Returns:
        Number of deleted rows (0 if the project store is not initialised
        or no rows matched).
    """
    if paths.root is None:
        return 0
    key = _project_key(paths)
    if key not in _per_project:
        return 0
    table = _per_project[key][1]
    # Escape single quotes so a path containing one cannot break the SQL
    # predicate nor inject arbitrary filter logic.
    escaped = raw_path.replace("'", "''")
    return table.delete(f"path = '{escaped}'").num_deleted_rows


def current_project_paths() -> Optional[WikiPaths]:
    """Return the WikiPaths of the project most recently initialised."""
    if _current_project_key is None:
        return None
    return WikiPaths(Path(_current_project_key))


def close_vector_store() -> None:
    """Drop in-memory handles — does NOT delete the on-disk database."""
    global _current_project_key
    _per_project.clear()
    _current_project_key = None


def __reset_for_testing() -> None:
    """Test-only reset — drops all per-project state."""
    global _current_project_key
    _per_project.clear()
    _current_project_key = None
