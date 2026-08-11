"""Tests for page version history."""
from src.wiki.core.types import PageType, WikiPage
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.storage.page_writer import write_page
from src.wiki.core.paths import WikiPaths
from src.wiki.features.version_history import get_version_history, get_version


def test_first_write_no_snapshot(tmp_path):
    """When a page is written for the first time, no snapshot is created."""
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    write_page(paths, WikiPage(id="p1", title="First", type=PageType.ENTITY, body="v1"))
    assert get_version_history(paths, "p1") == []


def test_snapshot_created_on_overwrite(tmp_path):
    """Writing an existing page creates a snapshot of the previous content."""
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    write_page(paths, WikiPage(id="p1", title="v1", type=PageType.ENTITY, body="original"))
    write_page(paths, WikiPage(id="p1", title="v2", type=PageType.ENTITY, body="updated"))
    history = get_version_history(paths, "p1")
    assert len(history) == 1
    assert "original" in history[0]["content"]


def test_snapshot_stores_raw_markdown(tmp_path):
    """Snapshot captures the raw markdown content (frontmatter + body)."""
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    write_page(paths, WikiPage(id="p1", title="v1", type=PageType.ENTITY, body="raw body"))
    write_page(paths, WikiPage(id="p1", title="v2", type=PageType.ENTITY, body="new body"))
    history = get_version_history(paths, "p1")
    raw = history[0]["content"]
    assert "raw body" in raw
    assert "---" in raw
    assert "v1" in raw


def test_retention_keeps_last_10(tmp_path):
    """Only the 10 most recent snapshots are retained."""
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    write_page(paths, WikiPage(id="p1", title="init", type=PageType.ENTITY, body="v0"))
    for i in range(1, 13):
        write_page(paths, WikiPage(id="p1", title=f"v{i}", type=PageType.ENTITY, body=f"v{i}"))
    history = get_version_history(paths, "p1")
    assert len(history) == 10
    # 13 writes → 12 snapshots (v0–v11 content). Retention 10 evicts oldest 2 (v0, v1).
    # Oldest retained snapshot contains v2 body, newest contains v11 body.
    assert "v2" in history[0]["content"]
    assert "v11" in history[-1]["content"]


def test_two_writes_produce_one_snapshot(tmp_path):
    """Writing twice produces exactly one snapshot (of the first version)."""
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    write_page(paths, WikiPage(id="p1", title="A", type=PageType.ENTITY, body="first"))
    write_page(paths, WikiPage(id="p1", title="B", type=PageType.ENTITY, body="second"))
    history = get_version_history(paths, "p1")
    assert len(history) == 1
    assert history[0]["content"].count("---") >= 2  # has frontmatter delimiters


def test_get_single_version(tmp_path):
    """get_version returns a specific snapshot by filename."""
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    write_page(paths, WikiPage(id="p1", title="v1", type=PageType.ENTITY, body="first"))
    write_page(paths, WikiPage(id="p1", title="v2", type=PageType.ENTITY, body="second"))
    history = get_version_history(paths, "p1")
    fname = history[0]["_filename"]
    snap = get_version(paths, "p1", fname)
    assert snap is not None
    assert "first" in snap["content"]


def test_get_version_nonexistent(tmp_path):
    """get_version returns None for missing version."""
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    assert get_version(paths, "p1", "nonexistent.json") is None
