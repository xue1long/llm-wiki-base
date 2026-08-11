"""Knowledge OS storage layer — object store, metadata, and wiki adapter."""

from src.knowledge.storage.metadata import (
    FilesystemMetadataStore,
    MetadataStore,
    PostgresMetadataStore,
)
from src.knowledge.storage.object_store import (
    LocalObjectStore,
    ObjectStore,
    S3ObjectStore,
)
from src.knowledge.storage.wiki_adapter import WikiPageAdapter

__all__ = [
    # Object store (raw files / media)
    "ObjectStore",
    "LocalObjectStore",
    "S3ObjectStore",
    # Metadata (knowledge-object CRUD)
    "MetadataStore",
    "FilesystemMetadataStore",
    "PostgresMetadataStore",
    "WikiPageAdapter",
]
