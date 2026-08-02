"""Metadata storage — abstract interface + filesystem and PostgreSQL backends.

``FilesystemMetadataStore`` is the DEFAULT backend, preserving the Phase 1-4
behaviour of reading/writing WikiPage markdown files under ``wiki/``.

``PostgresMetadataStore`` is for multi-instance deployments.  It is only used
when config ``storage.backend = "postgresql"`` and requires a ``DATABASE_URL``
environment variable.  psycopg2 is an *optional* dependency — not listed in
pyproject.toml.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod

from ...wiki.core.paths import WikiPaths
from ...wiki.core.types import PageType, WikiPage
from .wiki_adapter import WikiPageAdapter


class MetadataStore(ABC):
    """Abstract metadata storage — KnowledgeObject CRUD."""

    @abstractmethod
    def read(self, object_id: str) -> dict | None:
        """Return frontmatter dict + ``"body"`` key, or None if not found."""
        ...

    @abstractmethod
    def write(self, object_id: str, frontmatter: dict, body: str) -> None:
        """Create or overwrite a knowledge object."""
        ...

    @abstractmethod
    def delete(self, object_id: str) -> None:
        """Remove a knowledge object (move to archive for filesystem)."""
        ...

    @abstractmethod
    def list_all(self) -> list[str]:
        """Return every stored object ID."""
        ...

    @abstractmethod
    def count(self) -> int:
        """Return total number of stored objects."""
        ...

    @abstractmethod
    def exists(self, object_id: str) -> bool:
        """Return True if *object_id* is stored."""
        ...


class FilesystemMetadataStore(MetadataStore):
    """Thin wrapper over existing page_writer / WikiPage.

    This is the DEFAULT backend.  Phase 1-4 behaviour is unchanged:
    reads/writes WikiPage markdown files to ``wiki/`` subdirectories.
    """

    def __init__(self, wiki_paths: WikiPaths) -> None:
        self._paths = wiki_paths
        self._adapter = WikiPageAdapter(wiki_paths)

    # ------------------------------------------------------------------
    # MetadataStore interface
    # ------------------------------------------------------------------

    def read(self, object_id: str) -> dict | None:
        """Read .md file, parse frontmatter + body.  Returns None if missing."""
        page = self._adapter.read_page(object_id)
        if page is None:
            return None
        result = page.to_frontmatter_dict()
        result["body"] = page.body
        return result

    def write(self, object_id: str, frontmatter: dict, body: str) -> None:
        """Write .md file via safe_write.

        The *frontmatter* dict must contain at minimum ``type`` and ``title``.
        *object_id* is used as the page slug (filename stem).
        """
        fm = dict(frontmatter)
        fm["id"] = object_id
        # Default type to "concept" when absent so write succeeds.
        if "type" not in fm:
            fm["type"] = "concept"
        page = WikiPage.from_dict(fm, body=body)
        self._adapter.write_page(page)

    def delete(self, object_id: str) -> None:
        """Move page to ``wiki/_archive/``."""
        self._adapter.delete_page(object_id)

    def list_all(self) -> list[str]:
        """Walk ``wiki/`` subdirectories, return all page IDs."""
        return self._adapter.list_pages()

    def count(self) -> int:
        """Return the number of pages in all wiki subdirectories."""
        return len(self._adapter.list_pages())

    def exists(self, object_id: str) -> bool:
        """Check if a .md file exists for *object_id*."""
        return self._adapter.read_page(object_id) is not None


class PostgresMetadataStore(MetadataStore):
    """PostgreSQL-backed metadata storage for multi-instance deployments.

    Schema::

        CREATE TABLE knowledge_objects (
            id          TEXT PRIMARY KEY,
            type        TEXT NOT NULL,
            title       TEXT NOT NULL,
            frontmatter JSONB NOT NULL DEFAULT '{}',
            body        TEXT NOT NULL DEFAULT '',
            created_at  BIGINT NOT NULL,
            updated_at  BIGINT NOT NULL
        );

    Only used when config ``storage.backend = "postgresql"``.
    Requires ``DATABASE_URL`` environment variable and ``psycopg2``
    (or ``psycopg2-binary``) installed.
    """

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._conn = None  # lazy — connected on first operation

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    def _ensure_connection(self) -> None:
        """Lazy-connect to PostgreSQL.  Raises ImportError if psycopg2 is
        not installed."""
        if self._conn is not None:
            return
        try:
            import psycopg2 as _pg
        except ImportError:
            raise ImportError(
                "psycopg2 is required for PostgreSQL metadata storage. "
                "Install it with: pip install psycopg2-binary"
            ) from None
        self._conn = _pg.connect(self._database_url)

    def _ensure_table(self) -> None:
        """CREATE TABLE IF NOT EXISTS."""
        self._ensure_connection()
        with self._conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_objects (
                    id          TEXT PRIMARY KEY,
                    type        TEXT NOT NULL,
                    title       TEXT NOT NULL,
                    frontmatter JSONB NOT NULL DEFAULT '{}',
                    body        TEXT NOT NULL DEFAULT '',
                    created_at  BIGINT NOT NULL,
                    updated_at  BIGINT NOT NULL
                )
                """
            )
        self._conn.commit()

    # ------------------------------------------------------------------
    # MetadataStore interface
    # ------------------------------------------------------------------

    def read(self, object_id: str) -> dict | None:
        """Read a row from PostgreSQL.  Returns None if not found."""
        self._ensure_table()
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT frontmatter, body FROM knowledge_objects WHERE id = %s",
                (object_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        fm = dict(row[0])  # JSONB deserialised to dict by psycopg2
        fm["body"] = row[1]
        return fm

    def write(self, object_id: str, frontmatter: dict, body: str) -> None:
        """INSERT … ON CONFLICT UPDATE (upsert)."""
        self._ensure_table()
        fm = dict(frontmatter)
        fm["id"] = object_id
        type_ = fm.get("type", "concept")
        title = fm.get("title", object_id)
        created_at = fm.get("created_at", 0)
        updated_at = fm.get("updated_at", 0)
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO knowledge_objects (id, type, title, frontmatter, body, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    type        = EXCLUDED.type,
                    title       = EXCLUDED.title,
                    frontmatter = EXCLUDED.frontmatter,
                    body        = EXCLUDED.body,
                    created_at  = EXCLUDED.created_at,
                    updated_at  = EXCLUDED.updated_at
                """,
                (object_id, type_, title, json.dumps(fm), body, created_at, updated_at),
            )
        self._conn.commit()

    def delete(self, object_id: str) -> None:
        """DELETE a row by ID (no-op if not found)."""
        self._ensure_table()
        with self._conn.cursor() as cur:
            cur.execute(
                "DELETE FROM knowledge_objects WHERE id = %s",
                (object_id,),
            )
        self._conn.commit()

    def list_all(self) -> list[str]:
        """Return every ID in the table."""
        self._ensure_table()
        with self._conn.cursor() as cur:
            cur.execute("SELECT id FROM knowledge_objects ORDER BY id")
            return [row[0] for row in cur.fetchall()]

    def count(self) -> int:
        """Return row count."""
        self._ensure_table()
        with self._conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM knowledge_objects")
            return cur.fetchone()[0]

    def exists(self, object_id: str) -> bool:
        """Check if a row exists for *object_id*."""
        self._ensure_table()
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM knowledge_objects WHERE id = %s",
                (object_id,),
            )
            return cur.fetchone() is not None
