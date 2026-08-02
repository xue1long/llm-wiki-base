"""Tests for StorageFacade — unified storage with config-driven backend selection."""

import os
from pathlib import Path

import pytest

from src.knowledge.storage.event_store import (
    JSONLEventStore,
    PostgresEventStore,
)
from src.knowledge.storage.metadata import (
    FilesystemMetadataStore,
    PostgresMetadataStore,
)
from src.knowledge.storage.object_store import (
    LocalObjectStore,
    S3ObjectStore,
)
from src.knowledge.storage.facade import StorageConfig, StorageFacade


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_paths(tmp_path, name="test_project"):
    """Create wiki/ and .index/ directories under a temp project root.

    Returns (wiki_root, index_path) as two Paths.
    """
    root = tmp_path / name
    wiki_dir = root / "wiki"
    index_dir = root / ".index"
    for sub in ("sources", "entities", "concepts", "synthesis", "_stubs"):
        (wiki_dir / sub).mkdir(parents=True, exist_ok=True)
    index_dir.mkdir(parents=True, exist_ok=True)
    return root, index_dir


_SAMPLE_FM = {
    "type": "concept",
    "title": "Test Concept",
    "sources": [],
    "created_at": 1000,
    "updated_at": 2000,
    "grade": "A",
    "processing_depth": "concept",
    "is_immutable": False,
    "heat": 75,
    "last_used_at": 0,
    "zombie_since": None,
    "tags": ["test"],
}


# ---------------------------------------------------------------------------
# StorageConfig dataclass
# ---------------------------------------------------------------------------


class TestStorageConfigDefaults:
    """Verify StorageConfig default values."""

    def test_all_defaults_correct(self):
        cfg = StorageConfig()
        assert cfg.backend == "filesystem"
        assert cfg.object_store_backend == "local"
        assert cfg.event_store_backend == "jsonl"
        assert cfg.postgresql_url == ""
        assert cfg.s3_endpoint_url == ""
        assert cfg.s3_bucket == ""
        assert cfg.s3_access_key == ""
        assert cfg.s3_secret_key == ""
        assert cfg.wiki_path is None
        assert cfg.index_path is None

    def test_all_fields_present(self):
        """Every field listed in the spec is present."""
        fields = {
            f.name
            for f in StorageConfig.__dataclass_fields__.values()  # type: ignore[attr-defined]
        }
        expected = {
            "backend",
            "object_store_backend",
            "event_store_backend",
            "postgresql_url",
            "s3_endpoint_url",
            "s3_bucket",
            "s3_access_key",
            "s3_secret_key",
            "wiki_path",
            "index_path",
        }
        assert fields == expected

    def test_can_set_fields(self):
        cfg = StorageConfig(
            backend="postgresql",
            postgresql_url="pg://localhost/db",
            wiki_path=Path("/tmp/root"),
            index_path=Path("/tmp/root/.index"),
        )
        assert cfg.backend == "postgresql"
        assert cfg.postgresql_url == "pg://localhost/db"
        assert cfg.wiki_path == Path("/tmp/root")
        assert cfg.index_path == Path("/tmp/root/.index")


# ---------------------------------------------------------------------------
# StorageFacade — default (all-local) construction
# ---------------------------------------------------------------------------


class TestFacadeDefaultAllLocal:
    """With default StorageConfig, all stores are local/filesystem/JSONL."""

    @pytest.fixture
    def facade(self, tmp_path):
        root, index = _make_paths(tmp_path)
        config = StorageConfig(wiki_path=root, index_path=index)
        return StorageFacade(config)

    def test_metadata_is_filesystem(self, facade):
        assert isinstance(facade.metadata, FilesystemMetadataStore)

    def test_objects_is_local(self, facade):
        assert isinstance(facade.objects, LocalObjectStore)

    def test_events_is_jsonl(self, facade):
        assert isinstance(facade.events, JSONLEventStore)

    def test_get_config_returns_correct_config(self, facade, tmp_path):
        root, index = _make_paths(tmp_path)
        cfg = facade.get_config()
        assert cfg.wiki_path == root
        assert cfg.index_path == index
        assert cfg.backend == "filesystem"
        assert cfg.object_store_backend == "local"
        assert cfg.event_store_backend == "jsonl"


# ---------------------------------------------------------------------------
# StorageFacade — PostgreSQL metadata backend
# ---------------------------------------------------------------------------


class TestFacadePostgresqlMetadata:
    """When backend="postgresql" and URL is set, PostgresMetadataStore is used."""

    def test_backend_postgresql_uses_postgres_store(self, tmp_path):
        root, index = _make_paths(tmp_path)
        config = StorageConfig(
            backend="postgresql",
            postgresql_url="postgresql://user:pass@localhost/db",
            wiki_path=root,
            index_path=index,
        )
        facade = StorageFacade(config)
        assert isinstance(facade.metadata, PostgresMetadataStore)

    def test_backend_postgresql_no_url_falls_back_to_filesystem(self, tmp_path):
        root, index = _make_paths(tmp_path)
        config = StorageConfig(
            backend="postgresql",
            postgresql_url="",  # no URL — should fall back
            wiki_path=root,
            index_path=index,
        )
        facade = StorageFacade(config)
        assert isinstance(facade.metadata, FilesystemMetadataStore)


# ---------------------------------------------------------------------------
# StorageFacade — S3 object store backend
# ---------------------------------------------------------------------------


class TestFacadeS3ObjectStore:
    """When object_store_backend="s3", S3ObjectStore is used."""

    def test_object_store_s3_uses_s3_store(self, tmp_path):
        root, index = _make_paths(tmp_path)
        config = StorageConfig(
            object_store_backend="s3",
            s3_endpoint_url="http://localhost:9000",
            s3_bucket="test-bucket",
            wiki_path=root,
            index_path=index,
        )
        facade = StorageFacade(config)
        assert isinstance(facade.objects, S3ObjectStore)

    def test_s3_fallback_is_local_store(self, tmp_path):
        root, index = _make_paths(tmp_path)
        config = StorageConfig(
            object_store_backend="s3",
            s3_endpoint_url="http://localhost:9000",
            s3_bucket="test-bucket",
            wiki_path=root,
            index_path=index,
        )
        facade = StorageFacade(config)
        store = facade.objects
        assert isinstance(store, S3ObjectStore)
        # S3ObjectStore should have a LocalObjectStore fallback
        assert store._fallback is not None
        assert isinstance(store._fallback, LocalObjectStore)


# ---------------------------------------------------------------------------
# StorageFacade — PostgreSQL event store backend
# ---------------------------------------------------------------------------


class TestFacadePostgresqlEventStore:
    """When event_store_backend="postgresql" and URL is set, PostgresEventStore is used."""

    def test_event_store_postgresql_uses_postgres_store(self, tmp_path):
        root, index = _make_paths(tmp_path)
        config = StorageConfig(
            event_store_backend="postgresql",
            postgresql_url="postgresql://user:pass@localhost/db",
            wiki_path=root,
            index_path=index,
        )
        facade = StorageFacade(config)
        assert isinstance(facade.events, PostgresEventStore)

    def test_event_store_postgresql_no_url_falls_back_to_jsonl(self, tmp_path):
        root, index = _make_paths(tmp_path)
        config = StorageConfig(
            event_store_backend="postgresql",
            postgresql_url="",  # no URL
            wiki_path=root,
            index_path=index,
        )
        facade = StorageFacade(config)
        assert isinstance(facade.events, JSONLEventStore)


# ---------------------------------------------------------------------------
# StorageFacade — from_env factory
# ---------------------------------------------------------------------------


class TestFacadeFromEnv:
    """from_env() reads environment variables, safe-defaults when absent."""

    def test_no_env_vars_all_local(self, tmp_path, monkeypatch):
        """With no env vars set, all stores are local."""
        root, index = _make_paths(tmp_path)
        # Ensure env vars are cleared
        for var in (
            "DATABASE_URL",
            "STORAGE_BACKEND",
            "STORAGE_OBJECT_STORE_BACKEND",
            "STORAGE_EVENT_STORE_BACKEND",
            "S3_ENDPOINT_URL",
            "S3_BUCKET",
            "S3_ACCESS_KEY",
            "S3_SECRET_KEY",
        ):
            monkeypatch.delenv(var, raising=False)

        facade = StorageFacade.from_env(wiki_path=root, index_path=index)
        assert isinstance(facade.metadata, FilesystemMetadataStore)
        assert isinstance(facade.objects, LocalObjectStore)
        assert isinstance(facade.events, JSONLEventStore)

    def test_database_url_is_read(self, tmp_path, monkeypatch):
        """DATABASE_URL env var is passed to config."""
        root, index = _make_paths(tmp_path)
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
        monkeypatch.setenv("STORAGE_BACKEND", "postgresql")

        facade = StorageFacade.from_env(wiki_path=root, index_path=index)
        cfg = facade.get_config()
        assert cfg.postgresql_url == "postgresql://localhost/test"
        assert cfg.backend == "postgresql"
        assert isinstance(facade.metadata, PostgresMetadataStore)

    def test_storage_backend_env_is_read(self, tmp_path, monkeypatch):
        root, index = _make_paths(tmp_path)
        monkeypatch.setenv("STORAGE_BACKEND", "postgresql")
        monkeypatch.setenv("DATABASE_URL", "pg://host/db")

        facade = StorageFacade.from_env(wiki_path=root, index_path=index)
        cfg = facade.get_config()
        assert cfg.backend == "postgresql"

    def test_s3_env_vars_are_read(self, tmp_path, monkeypatch):
        root, index = _make_paths(tmp_path)
        monkeypatch.setenv("STORAGE_OBJECT_STORE_BACKEND", "s3")
        monkeypatch.setenv("S3_ENDPOINT_URL", "http://s3.example.com")
        monkeypatch.setenv("S3_BUCKET", "my-bucket")
        monkeypatch.setenv("S3_ACCESS_KEY", "AKID")
        monkeypatch.setenv("S3_SECRET_KEY", "secret")

        facade = StorageFacade.from_env(wiki_path=root, index_path=index)
        cfg = facade.get_config()
        assert cfg.object_store_backend == "s3"
        assert cfg.s3_endpoint_url == "http://s3.example.com"
        assert cfg.s3_bucket == "my-bucket"
        assert cfg.s3_access_key == "AKID"
        assert cfg.s3_secret_key == "secret"

    def test_event_store_env_is_read(self, tmp_path, monkeypatch):
        root, index = _make_paths(tmp_path)
        monkeypatch.setenv("STORAGE_EVENT_STORE_BACKEND", "postgresql")
        monkeypatch.setenv("DATABASE_URL", "pg://host/db")

        facade = StorageFacade.from_env(wiki_path=root, index_path=index)
        cfg = facade.get_config()
        assert cfg.event_store_backend == "postgresql"


# ---------------------------------------------------------------------------
# StorageFacade — delegation (end-to-end via metadata)
# ---------------------------------------------------------------------------


class TestFacadeDelegation:
    """Write via facade.metadata → read back.  Confirms delegate chain."""

    def test_write_then_read_through_facade(self, tmp_path):
        root, index = _make_paths(tmp_path)
        config = StorageConfig(wiki_path=root, index_path=index)
        facade = StorageFacade(config)

        fm = dict(_SAMPLE_FM)
        facade.metadata.write("e2e-test", fm, "End-to-end body.")

        result = facade.metadata.read("e2e-test")
        assert result is not None
        assert result["id"] == "e2e-test"
        assert result["title"] == "Test Concept"
        assert result["body"] == "End-to-end body."

    def test_facade_exists_and_list_all(self, tmp_path):
        root, index = _make_paths(tmp_path)
        config = StorageConfig(wiki_path=root, index_path=index)
        facade = StorageFacade(config)

        fm = dict(_SAMPLE_FM)
        facade.metadata.write("a", fm, "A")
        facade.metadata.write("b", fm, "B")

        assert facade.metadata.exists("a") is True
        assert facade.metadata.exists("c") is False
        assert sorted(facade.metadata.list_all()) == ["a", "b"]
        assert facade.metadata.count() == 2

    def test_facade_delete(self, tmp_path):
        root, index = _make_paths(tmp_path)
        config = StorageConfig(wiki_path=root, index_path=index)
        facade = StorageFacade(config)

        fm = dict(_SAMPLE_FM)
        facade.metadata.write("del-me", fm, "Delete me.")
        assert facade.metadata.exists("del-me") is True

        facade.metadata.delete("del-me")
        assert facade.metadata.exists("del-me") is False


# ---------------------------------------------------------------------------
# Phase 1-4 backward compatibility
# ---------------------------------------------------------------------------


class TestPhase1To4BehaviorUnchanged:
    """With all defaults, storage behaves identically to direct store usage."""

    def test_same_as_direct_filesystem_metadata_store(self, tmp_path):
        root, index = _make_paths(tmp_path)
        fm = dict(_SAMPLE_FM)

        # Direct usage
        from src.wiki.core.paths import WikiPaths

        direct = FilesystemMetadataStore(WikiPaths(root=root))
        direct.write("direct-test", fm, "Direct body.")
        direct_result = direct.read("direct-test")

        # Through facade
        config = StorageConfig(wiki_path=root, index_path=index)
        facade = StorageFacade(config)
        facade.metadata.write("facade-test", fm, "Facade body.")
        facade_result = facade.metadata.read("facade-test")

        # Both work the same way
        assert direct_result is not None
        assert facade_result is not None
        assert direct_result["id"] == "direct-test"
        assert facade_result["id"] == "facade-test"
        assert direct_result["body"] == "Direct body."
        assert facade_result["body"] == "Facade body."

    def test_default_facade_metadata_is_filesystem(self, tmp_path):
        root, index = _make_paths(tmp_path)
        config = StorageConfig(wiki_path=root, index_path=index)
        facade = StorageFacade(config)
        # With defaults, the facade should use filesystem for everything
        assert isinstance(facade.metadata, FilesystemMetadataStore)
        assert isinstance(facade.objects, LocalObjectStore)
        assert isinstance(facade.events, JSONLEventStore)

    def test_facade_does_not_require_db_or_s3(self, tmp_path):
        """Facade works with zero external dependencies (no psycopg2, no boto3)."""
        root, index = _make_paths(tmp_path)
        config = StorageConfig(wiki_path=root, index_path=index)
        facade = StorageFacade(config)
        # Should not raise — fully local
        assert facade.metadata.count() == 0
        assert facade.events.count() == 0


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestFacadeErrorCases:
    """Verify clear errors on missing required paths."""

    def test_missing_wiki_path_for_filesystem_raises(self):
        config = StorageConfig(wiki_path=None, index_path=Path("/tmp/.index"))
        with pytest.raises(ValueError, match="wiki_path"):
            StorageFacade(config)

    def test_missing_index_path_for_local_object_store_raises(self, tmp_path):
        root, _index = _make_paths(tmp_path)
        config = StorageConfig(wiki_path=root, index_path=None)
        with pytest.raises(ValueError, match="index_path"):
            StorageFacade(config)

    def test_missing_index_path_for_jsonl_event_store_raises(self, tmp_path):
        root, _index = _make_paths(tmp_path)
        config = StorageConfig(
            wiki_path=root,
            index_path=None,
            object_store_backend="s3",  # bypasses LocalObjectStore
        )
        with pytest.raises(ValueError, match="index_path"):
            StorageFacade(config)
