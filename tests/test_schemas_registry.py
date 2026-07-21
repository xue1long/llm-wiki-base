import pytest
from src.schemas.registry import (
    Migration, MIGRATIONS, register_migration,
    get_migration, migrate_data, CURRENT_VERSION
)

def test_register_and_get_migration():
    up_fn = lambda d: {**d, "schema_version": "v2.0"}
    down_fn = lambda d: {k: v for k, v in d.items() if k != "schema_version"}
    register_migration("v1.0", "v2.0", up_fn, down_fn)

    mig = get_migration("v1.0", "v2.0")
    assert mig is not None
    assert mig.from_version == "v1.0"
    assert mig.to_version == "v2.0"

def test_migrate_data_up():
    up_fn = lambda d: {**d, "schema_version": "v2.0", "upgraded": True}
    down_fn = lambda d: {k: v for k, v in d.items() if k not in ("schema_version", "upgraded")}
    register_migration("v1.0", "v2.0", up_fn, down_fn)

    data = {"title": "test", "schema_version": "v1.0"}
    result = migrate_data(data, "v2.0")
    assert result["schema_version"] == "v2.0"
    assert result["upgraded"] is True
    assert result["title"] == "test"

def test_migrate_same_version_returns_original():
    data = {"schema_version": "v2.0", "title": "test"}
    result = migrate_data(data, "v2.0")
    assert result == data

def test_migrate_unknown_version_raises():
    data = {"schema_version": "v99.0"}
    with pytest.raises(ValueError, match="No migration path"):
        migrate_data(data, "v2.0")

def test_migration_up_and_down():
    up_fn = lambda d: {**d, "schema_version": "v2.0"}
    down_fn = lambda d: {k: v for k, v in d.items() if k != "schema_version"}
    register_migration("v1.0", "v2.0", up_fn, down_fn)

    mig = get_migration("v1.0", "v2.0")
    original = {"title": "test", "schema_version": "v1.0"}
    migrated = mig.up(original)
    assert migrated["schema_version"] == "v2.0"

    original_restored = mig.down(migrated)
    assert "schema_version" not in original_restored
    assert original_restored["title"] == "test"