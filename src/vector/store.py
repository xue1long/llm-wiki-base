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

from ..wiki.core.paths import WikiPaths

import lancedb
import pyarrow as pa


# ---------------------------------------------------------------------------
# Per-project state
# ---------------------------------------------------------------------------
# ``_per_project`` maps ``str(paths.root.resolve())`` -> ``(db, table)``.
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
        ("embedding", pa.list_(pa.float32(), 1536)),
        ("path", pa.string()),
        ("updated_at", pa.int64()),
    ])


def _project_key(paths: WikiPaths) -> str:
    """Stable identifier for a project root — uses the resolved path string."""
    return str(paths.root.resolve())


def init_vector_store_for_paths(paths: WikiPaths) -> None:
    """Open (or reuse) the LanceDB handle for ``paths.root``.

    * If a handle is already cached for this project, it is reused and
      ``_current_project_key`` is updated to point at it.
    * Otherwise the handle is opened freshly and added to ``_per_project``.
    Other projects' handles are left untouched.

    LanceDB files are persisted at ``paths.index / "lancedb"``.
    """
    global _current_project_key
    key = _project_key(paths)
    if key not in _per_project:
        db_dir = paths.index / "lancedb"
        db_dir.mkdir(parents=True, exist_ok=True)

        db = lancedb.connect(str(db_dir))
        table = db.create_table("chunks", schema=_build_schema(), exist_ok=True)
        _per_project[key] = (db, table)
    _current_project_key = key


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
