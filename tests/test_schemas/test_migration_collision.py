# tests/test_schemas/test_migration_collision.py
"""Tests for MigrationRegistry.register() collision detection.

Per C-18 (full audit): registering two migrations under the same
(schema_name, from_version, to_version) key must raise MigrationKeyCollision
rather than silently overwriting.
"""
import pytest

from src.schemas.migration import MigrationContext, MigrationPlan, MigrationResult, SchemaVersion
from src.schemas.registry import MigrationKeyCollision, MigrationRegistry, migrate_data


def _stub_migration(schema_name, from_v, to_v):
    """Build a minimal Migration-like object for the given key."""

    class _Stub:
        def __init__(self, schema_name, from_v, to_v):
            self.schema_name = schema_name
            self.from_version = from_v
            self.to_version = to_v

        def preview(self, ctx: MigrationContext) -> MigrationPlan:
            return MigrationPlan(
                from_version=self.from_version,
                to_version=self.to_version,
                steps=["stub"],
                affected_files=[],
                reversible=True,
            )

        def up(self, ctx: MigrationContext) -> MigrationResult:
            return MigrationResult(success=True)

        def down(self, ctx: MigrationContext) -> MigrationResult:
            return MigrationResult(success=True)

    return _Stub(schema_name, from_v, to_v)


def setup_function(_):
    """Test isolation: clear the registry between tests."""
    MigrationRegistry._clear()


def test_register_twice_raises_migration_key_collision():
    """register() raises MigrationKeyCollision on duplicate (schema, from, to)."""
    m1 = _stub_migration("wiki_page", SchemaVersion.V2_0, SchemaVersion.V2_1)
    MigrationRegistry.register("wiki_page", SchemaVersion.V2_0, SchemaVersion.V2_1, m1)

    m2 = _stub_migration("wiki_page", SchemaVersion.V2_0, SchemaVersion.V2_1)
    with pytest.raises(MigrationKeyCollision):
        MigrationRegistry.register(
            "wiki_page", SchemaVersion.V2_0, SchemaVersion.V2_1, m2
        )


def test_register_different_keys_does_not_raise():
    """register() allows migrations under different keys."""
    m1 = _stub_migration("wiki_page", SchemaVersion.V2_0, SchemaVersion.V2_1)
    m2 = _stub_migration("wiki_page", SchemaVersion.V2_1, SchemaVersion.V2_2)

    MigrationRegistry.register("wiki_page", SchemaVersion.V2_0, SchemaVersion.V2_1, m1)
    MigrationRegistry.register("wiki_page", SchemaVersion.V2_1, SchemaVersion.V2_2, m2)

    assert MigrationRegistry.get(
        "wiki_page", SchemaVersion.V2_0, SchemaVersion.V2_1
    ) is m1
    assert MigrationRegistry.get(
        "wiki_page", SchemaVersion.V2_1, SchemaVersion.V2_2
    ) is m2


def test_register_different_schemas_does_not_raise():
    """register() allows the same version range under different schema names."""
    m1 = _stub_migration("wiki_page", SchemaVersion.V2_0, SchemaVersion.V2_1)
    m2 = _stub_migration("other_schema", SchemaVersion.V2_0, SchemaVersion.V2_1)

    MigrationRegistry.register("wiki_page", SchemaVersion.V2_0, SchemaVersion.V2_1, m1)
    MigrationRegistry.register(
        "other_schema", SchemaVersion.V2_0, SchemaVersion.V2_1, m2
    )


def test_collision_message_includes_key():
    """MigrationKeyCollision message includes the colliding key for diagnostics."""
    m1 = _stub_migration("wiki_page", SchemaVersion.V2_0, SchemaVersion.V2_2)
    MigrationRegistry.register("wiki_page", SchemaVersion.V2_0, SchemaVersion.V2_2, m1)

    m2 = _stub_migration("wiki_page", SchemaVersion.V2_0, SchemaVersion.V2_2)
    with pytest.raises(MigrationKeyCollision) as excinfo:
        MigrationRegistry.register(
            "wiki_page", SchemaVersion.V2_0, SchemaVersion.V2_2, m2
        )
    msg = str(excinfo.value)
    assert "wiki_page" in msg
    assert "v2.0" in msg
    assert "v2.2" in msg


def test_migrate_data_raises_not_implemented():
    """migrate_data() raises NotImplementedError — use Migration classes instead."""
    with pytest.raises(NotImplementedError):
        migrate_data({}, SchemaVersion.V2_2)
