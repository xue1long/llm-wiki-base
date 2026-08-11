# src/schemas/registry.py
"""Schema + Migration registry — versioned migration routing."""
import logging
from typing import Any

from .migration import Migration, MigrationNotFoundError, SchemaVersion


_logger = logging.getLogger(__name__)


class MigrationKeyCollision(Exception):
    """Raised when two migrations register the same (schema, from, to) key.

    The `key` attribute holds the colliding tuple
    `(schema_name, from_version, to_version)` so callers can diagnose which
    key collided.
    """

    def __init__(self, key: tuple[str, SchemaVersion, SchemaVersion]):
        self.key = key
        schema_name, from_v, to_v = key
        super().__init__(
            f"Migration already registered for {schema_name} {from_v.value} → "
            f"{to_v.value} (key={key!r})"
        )


class MigrationRegistry:
    """Static registry of all available Migrations.

    Backed by in-memory dict; tests use _clear() for isolation.
    """
    _migrations: dict[tuple[str, SchemaVersion, SchemaVersion], Migration] = {}

    @classmethod
    def register(cls, schema_name: str, from_v: SchemaVersion, to_v: SchemaVersion, m: Migration) -> None:
        key = (schema_name, from_v, to_v)
        if key in cls._migrations:
            raise MigrationKeyCollision(key)
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
    def list_migrations(cls) -> list[tuple[str, str, str]]:
        """Return all registered migrations as (schema_name, from_version, to_version) tuples.

        Output is sorted by (schema_name, from_version, to_version) for deterministic ordering.
        Public accessor so route handlers do not need to touch the private _migrations dict.
        """
        return sorted(
            (s, f.value, t.value) for (s, f, t) in cls._migrations.keys()
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
    """Legacy dict-based migration API — deliberately raises.

    The current migration classes operate on file paths (see
    ``src/schemas/migrations/``) and cannot be safely applied to arbitrary
    dicts. Callers must use the file-based path: instantiate the appropriate
    ``Migration`` subclass, construct a ``MigrationContext`` with the
    project path + backup directory, and call ``.up(ctx)`` / ``.down(ctx)``.
    """
    raise NotImplementedError(
        "migrate_data() is a no-op legacy stub. Use the file-based migration "
        "classes in src.schemas.migrations (e.g. V2ToV2_2WikiPageMigration) "
        "via MigrationRegistry.get(...).up(ctx)."
    )
