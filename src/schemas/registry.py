# src/schemas/registry.py
"""Schema + Migration registry — versioned migration routing."""
import logging
from typing import Any

from .migration import Migration, MigrationNotFoundError, SchemaVersion


_logger = logging.getLogger(__name__)


class MigrationRegistry:
    """Static registry of all available Migrations.

    Backed by in-memory dict; tests use _clear() for isolation.
    """
    _migrations: dict[tuple[str, SchemaVersion, SchemaVersion], Migration] = {}

    @classmethod
    def register(cls, schema_name: str, from_v: SchemaVersion, to_v: SchemaVersion, m: Migration) -> None:
        key = (schema_name, from_v, to_v)
        cls._migrations[key] = m

    @classmethod
    def get(cls, schema_name: str, from_v: SchemaVersion, to_v: SchemaVersion) -> Migration:
        key = (schema_name, from_v, to_v)
        m = cls._migrations.get(key)
        if m is None:
            raise MigrationNotFoundError(f"No migration: {schema_name} {from_v} → {to_v}")
        return m

    @classmethod
    def migration_path(
        cls, schema_name: str, from_v: SchemaVersion, to_v: SchemaVersion
    ) -> list[Migration]:
        """BFS to find shortest migration path (may involve intermediate versions)."""
        if from_v == to_v:
            return []
        # Direct edge first
        try:
            return [cls.get(schema_name, from_v, to_v)]
        except MigrationNotFoundError:
            pass
        # BFS
        from collections import deque
        visited = {from_v}
        queue = deque([(from_v, [])])
        while queue:
            cur, path = queue.popleft()
            for (sname, f, t), mig in cls._migrations.items():
                if sname != schema_name or f != cur or t in visited:
                    continue
                new_path = path + [mig]
                if t == to_v:
                    return new_path
                visited.add(t)
                queue.append((t, new_path))
        raise MigrationNotFoundError(
            f"No migration path: {schema_name} {from_v} → {to_v}"
        )

    @classmethod
    def _clear(cls) -> None:
        """Test-only: clear registry."""
        cls._migrations.clear()


# Backwards-compat shims (existing API)
def register_migration(schema_name: str, from_v: SchemaVersion, to_v: SchemaVersion, m: Migration) -> None:
    MigrationRegistry.register(schema_name, from_v, to_v, m)


def get_migration(schema_name: str, from_v: SchemaVersion, to_v: SchemaVersion) -> Migration:
    return MigrationRegistry.get(schema_name, from_v, to_v)


def migrate_data(data: dict[str, Any], target: SchemaVersion = SchemaVersion.V1_0) -> dict:
    """Migrate dict-based data (legacy API)."""
    from .migration import _migrate_via_registry
    return _migrate_via_registry(data, target)


# Legacy module-level names preserved for backwards compat with old test imports
CURRENT_VERSION = SchemaVersion.V1_0.value
MIGRATIONS = MigrationRegistry._migrations