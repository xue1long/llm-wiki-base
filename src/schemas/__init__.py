# src/schemas/__init__.py
"""Schemas package — re-exports public API."""

# New API (v3)
from .migration import Migration, SchemaVersion
from .registry import (
    MigrationRegistry,
    MigrationNotFoundError,
    register_migration,
    get_migration,
    migrate_data,
)

# Backwards-compat: keep old names reachable
CURRENT_VERSION = SchemaVersion.V1_0.value
MIGRATIONS = MigrationRegistry._migrations

__all__ = [
    # New
    "Migration",
    "SchemaVersion",
    "MigrationRegistry",
    "MigrationNotFoundError",
    # Backwards-compat shims
    "register_migration",
    "get_migration",
    "migrate_data",
    "CURRENT_VERSION",
    "MIGRATIONS",
]