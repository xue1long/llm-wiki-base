# src/project/discovery.py
"""Auto-discovery of existing KB projects on first run.

Scans DEFAULT_SEARCH_PATHS for directories containing KB markers
(`.llm-wiki/project.json`, `.index/schema_version` for v2.0, or `Notes/`
subdir for v1.0).
"""
import logging
from pathlib import Path

from ..utils.path import safe_resolve

from .context import ProjectContext
from .registry import GlobalRegistryStore


_logger = logging.getLogger(__name__)


# Default search paths for first-run discovery.
# Tests can monkeypatch this to use tmp dirs.
DEFAULT_SEARCH_PATHS: list[Path] = [
    Path.home() / "Documents",
    Path.home() / "Notes",
    Path.home() / "Knowledge",
    Path.home() / "wiki",
    Path.cwd() / "knowledge",        # repo-relative knowledge/ (novel-wiki etc.)
]


def _path_exists(path: Path) -> bool:
    """Treat an unreadable optional path as unavailable to read-only probes."""
    try:
        return path.exists()
    except OSError:
        return False


def is_kb_root(path: Path) -> bool:
    """Detect if a directory is a KB root (v1.0 or v2.0).

    Current marker: <path>/.llm-wiki/project.json exists
    v2.0 legacy marker: <path>/.index/schema_version exists
    v1.0 marker: <path>/Notes/ subdir exists
    """
    path = Path(path)
    if (path / ".llm-wiki" / "project.json").is_file():
        return True
    if (path / ".index" / "schema_version").is_file():
        return True
    if (path / "Notes").is_dir():
        return True
    return False


def discover_existing_kbs() -> list[Path]:
    """Scan DEFAULT_SEARCH_PATHS (top-level + 1 level deeper) for KBs.

    Returns list of KB root paths. Empty if none found.
    """
    found: list[Path] = []
    seen: set[Path] = set()

    for base in DEFAULT_SEARCH_PATHS:
        if not _path_exists(base) or not base.is_dir():
            continue
        try:
            # base itself
            base_resolved = safe_resolve(base)
            if is_kb_root(base) and base_resolved not in seen:
                found.append(base_resolved)
                seen.add(base_resolved)
            # 1 level deeper
            for child in base.iterdir():
                if not child.is_dir():
                    continue
                child_resolved = safe_resolve(child)
                if is_kb_root(child) and child_resolved not in seen:
                    found.append(child_resolved)
                    seen.add(child_resolved)
        except PermissionError:
            _logger.warning(f"[discovery] permission denied: {base}")
            continue
    return found


def auto_register_on_first_run() -> list[ProjectContext]:
    """Discover KBs in DEFAULT_SEARCH_PATHS and register any not yet in the registry.

    Idempotent: already-registered projects are skipped (by_id returns existing entry).
    When registry.json doesn't exist, performs full discovery + registration.
    When registry.json exists, registers any new projects found in search paths.

    Returns list of newly registered ProjectContexts (may be empty).
    """
    from .registry import registry_path as _default_registry_path

    kb_paths = discover_existing_kbs()
    contexts: list[ProjectContext] = []
    for kb_path in kb_paths:
        try:
            # Guard against same-name-different-path confusion. When the
            # registry already contains a project with the same directory
            # name but pointing at a *different* physical path (e.g. the
            # repo was cloned/duplicated), skip it and warn instead of
            # silently registering a second same-named entity. This is the
            # root cause of "which project am I actually looking at" — two
            # registries both call it "novel-wiki" while pointing at
            # different copies on disk.
            if GlobalRegistryStore.by_path(kb_path) is None:
                collision = GlobalRegistryStore.by_name(kb_path.name)
                if collision is not None:
                    _logger.warning(
                        "[discovery] skipping %s: a project named %r already "
                        "exists at %s (candidate at %s was NOT registered)",
                        kb_path, collision.name, collision.path, kb_path,
                    )
                    continue
            ctx = ProjectContext.from_path(kb_path)  # from_path is idempotent (skips if exists)
            contexts.append(ctx)
        except Exception as e:
            _logger.warning(f"[discovery] failed to register {kb_path}: {e}")

    # Set last_project to most recently modified if registry was freshly created
    if not _path_exists(_default_registry_path()) and contexts:
        contexts.sort(key=lambda c: c.path.stat().st_mtime, reverse=True)
        GlobalRegistryStore.save_last_project(
            id=contexts[0].id,
            path=str(contexts[0].path),
        )

    return contexts
