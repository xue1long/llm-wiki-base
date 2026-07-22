# src/schemas/__init__.py
"""Schemas package — re-exports public API."""

# New API (v3)
from .migration import Migration
from .registry import (
    MigrationRegistry,
    MigrationNotFoundError,
    register_migration,
    get_migration,
    migrate_data,
)

__all__ = [
    "Migration",
    "MigrationRegistry",
    "MigrationNotFoundError",
    "register_migration",
    "get_migration",
    "migrate_data",
]