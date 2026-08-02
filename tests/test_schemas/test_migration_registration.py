"""Task 0.1 — verify v2.1 and v2.2 migrations are registered on import.

Because other tests call ``MigrationRegistry._clear()``, each test clears the
registry and then force-reimports the migration modules to re-trigger their
module-level ``MigrationRegistry.register()`` calls.
"""
import importlib
import sys

import pytest

from src.schemas.migration import SchemaVersion
from src.schemas.registry import MigrationRegistry, MigrationNotFoundError

# Imported directly (not via src.schemas) — not in the package re-exports
from src.schemas.registry import MigrationKeyCollision


def _reload_migrations():
    """Re-import all migration submodules so their register() calls re-fire.

    Uses importlib.reload for modules already in sys.modules, and fresh
    import for modules not yet loaded.  MigrationKeyCollision is tolerated
    (another test in the session may have already registered the same key).
    """
    for name in (
        "src.schemas.migrations.v1_to_v2",
        "src.schemas.migrations.v2_to_v2_1",
        "src.schemas.migrations.v2_to_v2_2",
    ):
        try:
            if name in sys.modules:
                importlib.reload(sys.modules[name])
            else:
                __import__(name)
        except MigrationKeyCollision:
            pass
    # Reload the package so __init__.py re-executes
    try:
        importlib.reload(sys.modules["src.schemas.migrations"])
    except MigrationKeyCollision:
        pass


def test_v2_0_to_v2_1_migration_registered():
    """get_migration for wiki_page v2.0→v2.1 must succeed after import."""
    MigrationRegistry._clear()
    _reload_migrations()
    m = MigrationRegistry.get("wiki_page", SchemaVersion.V2_0, SchemaVersion.V2_1)
    assert m is not None


def test_v2_0_to_v2_2_migration_registered():
    """get_migration for wiki_page v2.0→v2.2 must succeed after import."""
    MigrationRegistry._clear()
    _reload_migrations()
    m = MigrationRegistry.get("wiki_page", SchemaVersion.V2_0, SchemaVersion.V2_2)
    assert m is not None


def test_schema_list_includes_v21_and_v22():
    """Both v2.1 and v2.2 migrations are discoverable via registry.list()."""
    MigrationRegistry._clear()
    _reload_migrations()
    keys = MigrationRegistry.list_migrations()
    assert ("wiki_page", "v2.0", "v2.1") in keys
    assert ("wiki_page", "v2.0", "v2.2") in keys


def test_v2_0_to_v2_1_raises_after_clear():
    """After registry clear without re-import, get_migration raises."""
    MigrationRegistry._clear()
    with pytest.raises(MigrationNotFoundError):
        MigrationRegistry.get("wiki_page", SchemaVersion.V2_0, SchemaVersion.V2_1)
