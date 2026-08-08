# ruflo-kb/src/vector/store.py
"""Per-project LanceDB handle store.

There is one :class:`lancedb.LanceDB` (and a corresponding ``chunks`` table)
per project. ``init_vector_store_for_paths(paths)`` opens the handle for
``paths.root`` and stores it in a ``{path: (db, table)}`` map. ``get_table()``
returns the table for whichever project was most recently initialised
(``current_project_key``).

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


# ---------------------------------------------------------------------------
# Per-project state
# ---------------------------------------------------------------------------
# ``_per_project`` maps ``safe_resolve_str(paths.root)`` -> ``(db, table)``.
# A second project init does not affect the first project's handle.
_per_project: dict[str, tuple[Any, Any]] = {}
# ``current_project_key`` is the active project for ``get_table()`` and is
# updated every time ``init_vector_store_for_paths`` is called.
_current_project_key: Optional[str] = None


def _build_schema():
    """Build the LanceDB schema lazily.

    Schema construction uses ``pyarrow`` attributes (``.string``, ``.list_``,
    ``.float32``, etc.). Building it lazily inside :func:`init_vector_store_for_paths`
    instead of at module-import time keeps the module importable even when
    ``pyarrow`` is stubbed out by the test conftest hierarchy.
    """
    return pa.schema([
        ("id", pa.string()),
        ("task_id", pa.string()),
        ("content", pa.string()),
        ("embedding", pa.list_(pa.float32(), 384)),
        ("path", pa.string()),
        ("updated_at", pa.int64()),
    ])


def _project_key(paths: WikiPaths) -> str:
    """Stable identifier for a project root — safe from CJK corruption."""
    return safe_resolve_str(paths.root)


def init_vector_store_for_paths(paths: WikiPaths) -> None:
    """Open (or reuse) the LanceDB handle for ``paths.root``.

    * If a handle is already cached for this project, it is reused and
      ``_current_project_key`` is updated to point at it.
    * Otherwise the handle is opened freshly and added to ``_per_project``.
    Other projects' handles are left untouched.

    When the existing table schema has a different embedding dimension
    (e.g. old 1536-dim data when the code now expects 384-dim), the table
    is dropped and recreated automatically. This handles the migration
    from remote embedding providers (1536-dim) to the local
    sentence-transformers provider (384-dim).

    LanceDB files are persisted at ``paths.index / "lancedb"``.
    """
    global _current_project_key
    key = _project_key(paths)
    if key not in _per_project:
        db_dir = paths.index / "lancedb"
        db_dir.mkdir(parents=True, exist_ok=True)

        db = lancedb.connect(str(db_dir))

        # Detect stale dimension and drop + recreate if needed.
        _migrate_schema_if_needed(db)

        table = db.create_table("chunks", schema=_build_schema(), exist_ok=True)
        _per_project[key] = (db, table)
    _current_project_key = key


def _migrate_schema_if_needed(db: lancedb.LanceDB) -> None:
    """Drop the ``chunks`` table if its embedding dimension differs from 384.

    This handles the migration from 1536-dim remote providers (OpenAI,
    MiniMax) to 384-dim local sentence-transformers.  Silent no-op when
    the table does not exist, the dimension already matches, or the
    check fails for any reason.
    """
    expected_dim = 384
    try:
        existing = db.open_table("chunks")
        sample = existing.head(1)
        if len(sample) > 0:
            old_dim = len(sample["embedding"][0])
            if old_dim == expected_dim:
                return
            _logger.info(
                "[vector] detected schema dimension change: %d → %d; "
                "dropping and recreating table",
                old_dim, expected_dim,
            )
        else:
            _logger.info(
                "[vector] existing table has no rows; recreating with "
                "new schema (384-dim)"
            )
        db.drop_table("chunks")
    except Exception:
        pass  # table doesn't exist or can't be sampled — nothing to migrate


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
