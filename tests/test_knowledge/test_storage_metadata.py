"""Tests for src.knowledge.storage — MetadataStore + WikiPageAdapter."""

import pytest

from src.knowledge.storage.metadata import (
    FilesystemMetadataStore,
    MetadataStore,
    PostgresMetadataStore,
)
from src.knowledge.storage.wiki_adapter import WikiPageAdapter
from src.wiki.core.paths import WikiPaths
from src.wiki.core.types import PageType, WikiPage


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_paths(tmp_path):
    """Create a minimal WikiPaths structure and return it."""
    root = tmp_path / "test_project"
    paths = WikiPaths(root=root)
    for attr in (
        "wiki_sources",
        "wiki_entities",
        "wiki_concepts",
        "wiki_synthesis",
        "wiki_claims",
        "wiki_decisions",
        "wiki_stubs",
    ):
        getattr(paths, attr).mkdir(parents=True, exist_ok=True)
    return paths


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
    "category": "",
    "taxonomy_sub": "",
}


def _write_sample(store, oid="test-concept", fm=None, body="Hello world."):
    store.write(oid, fm if fm is not None else dict(_SAMPLE_FM), body)


# ---------------------------------------------------------------------------
# MetadataStore ABC
# ---------------------------------------------------------------------------


class TestMetadataStoreABC:
    def test_cannot_instantiate_abstract_class(self):
        with pytest.raises(TypeError):
            MetadataStore()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# FilesystemMetadataStore — write + read
# ---------------------------------------------------------------------------


class TestFilesystemWriteRead:
    def test_write_then_read_returns_correct_data(self, tmp_path):
        paths = _make_paths(tmp_path)
        store = FilesystemMetadataStore(paths)
        fm = dict(_SAMPLE_FM)
        _write_sample(store, "my-page", fm, "Body text.")
        result = store.read("my-page")
        assert result is not None
        assert result["id"] == "my-page"
        assert result["title"] == "Test Concept"
        assert result["type"] == "concept"
        assert result["body"] == "Body text."
        assert result["grade"] == "A"
        assert result["heat"] == 75

    def test_read_nonexistent_returns_none(self, tmp_path):
        paths = _make_paths(tmp_path)
        store = FilesystemMetadataStore(paths)
        assert store.read("no-such-page") is None

    def test_write_overwrite_same_id(self, tmp_path):
        paths = _make_paths(tmp_path)
        store = FilesystemMetadataStore(paths)
        _write_sample(store, "dup", body="First.")
        _write_sample(store, "dup", body="Second.")
        result = store.read("dup")
        assert result["body"] == "Second."

    def test_write_preserves_complex_frontmatter(self, tmp_path):
        paths = _make_paths(tmp_path)
        store = FilesystemMetadataStore(paths)
        fm = {
            "type": "entity",
            "title": "Complex Entity",
            "sources": ["src/a.pdf", "src/b.pdf"],
            "created_at": 999,
            "updated_at": 1111,
            "grade": "B",
            "processing_depth": "memory",
            "is_immutable": True,
            "heat": 30,
            "last_used_at": 500,
            "zombie_since": None,
            "tags": ["角色/女主角", "题材/都市"],
            "category": "characters",
            "taxonomy_sub": "protagonist",
        }
        _write_sample(store, "complex", fm, "Complex body.")
        result = store.read("complex")
        assert result["type"] == "entity"
        assert result["sources"] == ["src/a.pdf", "src/b.pdf"]
        assert result["grade"] == "B"
        assert result["processing_depth"] == "memory"
        assert result["is_immutable"] is True
        assert result["tags"] == ["角色/女主角", "题材/都市"]
        assert result["category"] == "characters"
        assert result["taxonomy_sub"] == "protagonist"

    def test_write_preserves_body_roundtrip(self, tmp_path):
        paths = _make_paths(tmp_path)
        store = FilesystemMetadataStore(paths)
        body = "# Heading\n\nSome **markdown** content.\n\n- item 1\n- item 2\n"
        _write_sample(store, "md-page", body=body)
        result = store.read("md-page")
        assert result["body"] == body

    def test_write_defaults_type_to_concept(self, tmp_path):
        paths = _make_paths(tmp_path)
        store = FilesystemMetadataStore(paths)
        # frontmatter without 'type'
        fm = {"title": "No Type Page"}
        store.write("no-type", fm, "Body.")
        result = store.read("no-type")
        assert result is not None
        assert result["type"] == "concept"


# ---------------------------------------------------------------------------
# FilesystemMetadataStore — exists
# ---------------------------------------------------------------------------


class TestFilesystemExists:
    def test_exists_after_write(self, tmp_path):
        paths = _make_paths(tmp_path)
        store = FilesystemMetadataStore(paths)
        assert store.exists("x") is False
        _write_sample(store, "x")
        assert store.exists("x") is True

    def test_exists_unknown(self, tmp_path):
        paths = _make_paths(tmp_path)
        store = FilesystemMetadataStore(paths)
        assert store.exists("unknown-id") is False


# ---------------------------------------------------------------------------
# FilesystemMetadataStore — list_all / count
# ---------------------------------------------------------------------------


class TestFilesystemListCount:
    def test_list_all_empty(self, tmp_path):
        paths = _make_paths(tmp_path)
        store = FilesystemMetadataStore(paths)
        assert store.list_all() == []
        assert store.count() == 0

    def test_list_all_three_objects(self, tmp_path):
        paths = _make_paths(tmp_path)
        store = FilesystemMetadataStore(paths)
        for oid in ("a", "b", "c"):
            _write_sample(store, oid)
        ids = store.list_all()
        assert sorted(ids) == ["a", "b", "c"]
        assert store.count() == 3

    def test_list_all_respects_page_types(self, tmp_path):
        """Pages in different type directories are all listed."""
        paths = _make_paths(tmp_path)
        store = FilesystemMetadataStore(paths)
        store.write("src-1", {"type": "source", "title": "S"}, "source body")
        store.write("ent-1", {"type": "entity", "title": "E"}, "entity body")
        store.write("con-1", {"type": "concept", "title": "C"}, "concept body")
        ids = store.list_all()
        assert sorted(ids) == ["con-1", "ent-1", "src-1"]
        assert store.count() == 3


# ---------------------------------------------------------------------------
# FilesystemMetadataStore — delete
# ---------------------------------------------------------------------------


class TestFilesystemDelete:
    def test_delete_removes_object(self, tmp_path):
        paths = _make_paths(tmp_path)
        store = FilesystemMetadataStore(paths)
        _write_sample(store, "to-delete")
        assert store.exists("to-delete") is True
        store.delete("to-delete")
        assert store.exists("to-delete") is False

    def test_delete_moves_to_archive(self, tmp_path):
        paths = _make_paths(tmp_path)
        store = FilesystemMetadataStore(paths)
        _write_sample(store, "archive-me", body="archive content")
        store.delete("archive-me")
        archive_file = paths.wiki / "_archive" / "archive-me.md"
        assert archive_file.exists()
        assert "archive content" in archive_file.read_text(encoding="utf-8")

    def test_delete_nonexistent_is_noop(self, tmp_path):
        paths = _make_paths(tmp_path)
        store = FilesystemMetadataStore(paths)
        # Should not raise
        store.delete("no-such-thing")


# ---------------------------------------------------------------------------
# WikiPageAdapter
# ---------------------------------------------------------------------------


class TestWikiPageAdapter:
    def test_read_write_basic(self, tmp_path):
        paths = _make_paths(tmp_path)
        adapter = WikiPageAdapter(paths)
        page = WikiPage(
            id="adapter-test",
            title="Adapter Test",
            type=PageType.CONCEPT,
            body="Adapter body.",
            grade="A",
        )
        adapter.write_page(page)
        result = adapter.read_page("adapter-test")
        assert result is not None
        assert result.id == "adapter-test"
        assert result.title == "Adapter Test"
        assert result.body == "Adapter body."
        assert result.grade == "A"

    def test_read_nonexistent(self, tmp_path):
        paths = _make_paths(tmp_path)
        adapter = WikiPageAdapter(paths)
        assert adapter.read_page("nope") is None

    def test_list_pages(self, tmp_path):
        paths = _make_paths(tmp_path)
        adapter = WikiPageAdapter(paths)
        adapter.write_page(
            WikiPage(id="x", title="X", type=PageType.CONCEPT, body="")
        )
        adapter.write_page(
            WikiPage(id="y", title="Y", type=PageType.ENTITY, body="")
        )
        ids = adapter.list_pages()
        assert sorted(ids) == ["x", "y"]

    def test_delete_page(self, tmp_path):
        paths = _make_paths(tmp_path)
        adapter = WikiPageAdapter(paths)
        adapter.write_page(
            WikiPage(id="del-me", title="Del", type=PageType.CONCEPT, body="bye")
        )
        assert adapter.read_page("del-me") is not None
        adapter.delete_page("del-me")
        assert adapter.read_page("del-me") is None
        archive = paths.wiki / "_archive" / "del-me.md"
        assert archive.exists()


# ---------------------------------------------------------------------------
# PostgresMetadataStore — interface check (no actual DB connection)
# ---------------------------------------------------------------------------


class TestPostgresMetadataStoreInterface:
    """Verify PostgresMetadataStore class structure without requiring PostgreSQL."""

    def test_class_exists_and_is_subclass(self):
        assert issubclass(PostgresMetadataStore, MetadataStore)

    def test_has_required_methods(self):
        store_class = PostgresMetadataStore
        for method_name in ("read", "write", "delete", "list_all", "count", "exists"):
            assert hasattr(store_class, method_name), f"missing method: {method_name}"
            m = getattr(store_class, method_name)
            assert callable(m), f"{method_name} is not callable"

    def test_init_accepts_database_url(self):
        store = PostgresMetadataStore("postgresql://user:pass@localhost/db")
        assert store._database_url == "postgresql://user:pass@localhost/db"
        assert store._conn is None  # lazy — not connected yet
