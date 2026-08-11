"""Storage facade — unified entry point with config-driven backend selection.

Encapsulates all storage backends and selects the active one based on
StorageConfig. Presents a single interface to the rest of the system
regardless of backend choice.

Usage::

    # Defaults — filesystem + local + JSONL (Phase 1-4 behaviour)
    facade = StorageFacade(StorageConfig(wiki_path=root, index_path=idx))

    # With env vars
    facade = StorageFacade.from_env(wiki_path=root, index_path=idx)

    facade.metadata.write("my-id", fm, body)
    data = facade.metadata.read("my-id")
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .event_store import JSONLEventStore, PostgresEventStore, EventStore
from .metadata import FilesystemMetadataStore, PostgresMetadataStore, MetadataStore
from .object_store import LocalObjectStore, S3ObjectStore, ObjectStore
from ...wiki.core.paths import WikiPaths


# ---------------------------------------------------------------------------
# StorageConfig
# ---------------------------------------------------------------------------


@dataclass
class StorageConfig:
    """Configuration for storage backends.

    All backends default to local/filesystem/jsonl — same behaviour as Phase 1-4.
    PostgreSQL and S3 are opt-in via config flags.
    """

    backend: str = "filesystem"
    """Metadata backend: ``"filesystem"`` (default) or ``"postgresql"``."""

    object_store_backend: str = "local"
    """Object/blob backend: ``"local"`` (default) or ``"s3"``."""

    event_store_backend: str = "jsonl"
    """Event backend: ``"jsonl"`` (default) or ``"postgresql"``."""

    postgresql_url: str = ""
    """DATABASE_URL for PostgreSQL backends. Required when backend/broadcaster uses postgresql."""

    s3_endpoint_url: str = ""
    s3_bucket: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""

    wiki_path: Path | None = None
    """Path to the project root (contains ``wiki/``, ``.index/``, etc.)."""

    index_path: Path | None = None
    """Path to ``.index/`` directory."""


# ---------------------------------------------------------------------------
# StorageFacade
# ---------------------------------------------------------------------------


class StorageFacade:
    """Unified storage entry point for KnowledgeKernel.

    Encapsulates all storage backends and selects the active one based on
    StorageConfig. Presents a single interface to the rest of the system
    regardless of backend choice.

    Architecture::

        Agent → KnowledgeKernel (permissions + lifecycle + events)
                   ↓
               StorageFacade (metadata CRUD + blob read/write + event append)
                   ↓
           ┌───────┼────────┐
           │       │         │
        PostgreSQL  S3    EventStore
        (metadata) (blobs) (events)

    Phase 1-4 behaviour is preserved when config uses defaults.
    """

    def __init__(self, config: StorageConfig) -> None:
        self._config = config
        self._metadata_store: MetadataStore | None = None
        self._object_store: ObjectStore | None = None
        self._event_store: EventStore | None = None
        self._init_stores()

    # ------------------------------------------------------------------
    # Backend selection
    # ------------------------------------------------------------------

    def _init_stores(self) -> None:
        """Initialize storage backends based on config."""
        # Metadata store
        if self._config.backend == "postgresql" and self._config.postgresql_url:
            self._metadata_store = PostgresMetadataStore(self._config.postgresql_url)
        else:
            if self._config.wiki_path is None:
                raise ValueError(
                    "wiki_path is required for filesystem metadata backend"
                )
            wiki_paths = WikiPaths(root=self._config.wiki_path)
            self._metadata_store = FilesystemMetadataStore(wiki_paths)

        # Object store
        if self._config.object_store_backend == "s3":
            index_path = self._config.index_path or Path(".")
            local_fallback = LocalObjectStore(index_path)
            self._object_store = S3ObjectStore(
                endpoint_url=self._config.s3_endpoint_url,
                bucket=self._config.s3_bucket,
                access_key=self._config.s3_access_key,
                secret_key=self._config.s3_secret_key,
                fallback=local_fallback,
            )
        else:
            if self._config.index_path is None:
                raise ValueError(
                    "index_path is required for local object store backend"
                )
            self._object_store = LocalObjectStore(self._config.index_path)

        # Event store
        if (
            self._config.event_store_backend == "postgresql"
            and self._config.postgresql_url
        ):
            self._event_store = PostgresEventStore(self._config.postgresql_url)
        else:
            if self._config.index_path is None:
                raise ValueError(
                    "index_path is required for JSONL event store backend"
                )
            self._event_store = JSONLEventStore(self._config.index_path)

    # ------------------------------------------------------------------
    # Properties — readonly access to active stores
    # ------------------------------------------------------------------

    @property
    def metadata(self) -> MetadataStore:
        """Active metadata store."""
        assert self._metadata_store is not None
        return self._metadata_store

    @property
    def objects(self) -> ObjectStore:
        """Active object store."""
        assert self._object_store is not None
        return self._object_store

    @property
    def events(self) -> EventStore:
        """Active event store."""
        assert self._event_store is not None
        return self._event_store

    # ------------------------------------------------------------------
    # Config introspection
    # ------------------------------------------------------------------

    def get_config(self) -> StorageConfig:
        """Return the current storage config."""
        return self._config

    # ------------------------------------------------------------------
    # Factory from environment
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls, wiki_path: Path, index_path: Path) -> "StorageFacade":
        """Create StorageFacade from environment variables + defaults.

        Reads::

            DATABASE_URL               → postgresql_url
            STORAGE_BACKEND            → backend
            STORAGE_OBJECT_STORE_BACKEND  → object_store_backend
            STORAGE_EVENT_STORE_BACKEND   → event_store_backend
            S3_ENDPOINT_URL            → s3_endpoint_url
            S3_BUCKET                  → s3_bucket
            S3_ACCESS_KEY              → s3_access_key
            S3_SECRET_KEY              → s3_secret_key

        Defaults to all-local when env vars are not set.
        """
        config = StorageConfig(
            backend=os.environ.get("STORAGE_BACKEND", "filesystem"),
            object_store_backend=os.environ.get(
                "STORAGE_OBJECT_STORE_BACKEND", "local"
            ),
            event_store_backend=os.environ.get(
                "STORAGE_EVENT_STORE_BACKEND", "jsonl"
            ),
            postgresql_url=os.environ.get("DATABASE_URL", ""),
            s3_endpoint_url=os.environ.get("S3_ENDPOINT_URL", ""),
            s3_bucket=os.environ.get("S3_BUCKET", ""),
            s3_access_key=os.environ.get("S3_ACCESS_KEY", ""),
            s3_secret_key=os.environ.get("S3_SECRET_KEY", ""),
            wiki_path=wiki_path,
            index_path=index_path,
        )
        return cls(config)
