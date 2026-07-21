# tests/test_schemas/test_registry.py
from src.schemas.migration import SchemaVersion
from src.schemas.registry import MigrationRegistry, MigrationNotFoundError


def test_register_and_get_migration():
    """register_migration stores a migration; get_migration retrieves it."""

    class MyMig:
        schema_name = "wiki_page"
        from_version = SchemaVersion.V1_0
        to_version = SchemaVersion.V2_0

        def preview(self, ctx): pass
        def up(self, ctx): pass
        def down(self, ctx): pass

    MigrationRegistry._clear()  # for test isolation
    MigrationRegistry.register("wiki_page", SchemaVersion.V1_0, SchemaVersion.V2_0, MyMig())
    m = MigrationRegistry.get("wiki_page", SchemaVersion.V1_0, SchemaVersion.V2_0)
    assert m is not None


def test_get_migration_not_found():
    MigrationRegistry._clear()
    with __import__("pytest").raises(MigrationNotFoundError):
        MigrationRegistry.get("wiki_page", SchemaVersion.V2_0, SchemaVersion.V3_0)


def test_migration_path_finds_hops():
    """migration_path() finds path V1.0 → V2.0 → V2.1."""
    MigrationRegistry._clear()

    class A:
        schema_name = "wiki_page"
        from_version = SchemaVersion.V1_0
        to_version = SchemaVersion.V2_0
        def preview(self, ctx): pass
        def up(self, ctx): pass
        def down(self, ctx): pass

    class B:
        schema_name = "wiki_page"
        from_version = SchemaVersion.V2_0
        to_version = SchemaVersion.V2_1
        def preview(self, ctx): pass
        def up(self, ctx): pass
        def down(self, ctx): pass

    MigrationRegistry.register("wiki_page", SchemaVersion.V1_0, SchemaVersion.V2_0, A())
    MigrationRegistry.register("wiki_page", SchemaVersion.V2_0, SchemaVersion.V2_1, B())

    path = MigrationRegistry.migration_path("wiki_page", SchemaVersion.V1_0, SchemaVersion.V2_1)
    assert len(path) == 2
    assert path[0].from_version == SchemaVersion.V1_0
    assert path[1].to_version == SchemaVersion.V2_1