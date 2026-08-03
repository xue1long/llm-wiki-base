"""Regression: services.ingest.enqueue_source normalizes absolute file paths.

Before this fix, an absolute file path like `/abs/project/raw/sources/foo.md`
was passed through verbatim, and Collector's permission check (which only
matches relative paths like `raw/sources`) raised PermissionError.
After this fix, the service anchors absolute paths to the project root
and rejects paths outside the project.

After the queue refactor (Tasks 1-7), persistence is handled by
JsonFileBackend via QueueService. The test redirects the backend's path
and clears the singleton between tests via __reset_for_testing().
"""
import pytest

from src.services import ingest as ingest_service
from src.queue import __reset_for_testing, get_default_queue_service


@pytest.fixture(autouse=True)
def _isolate_queue(tmp_path, monkeypatch):
    """Reset the singleton and redirect the backend's persistence path.

    Without this, the global queue persists between tests via
    .kb-queue.json and the first call to __reset_for_testing() reloads
    any tasks other tests had saved.
    """
    __reset_for_testing()
    yield
    __reset_for_testing()


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Set up a registered project pointing at tmp_path."""
    from src.project import paths as project_paths
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    monkeypatch.setattr(project_paths, "_OVERRIDE_CONFIG_DIR", cfg_dir)

    project_root = tmp_path / "kb"
    project_root.mkdir()
    (project_root / ".llm-wiki").mkdir()
    (project_root / ".llm-wiki" / "project.json").write_text(
        '''{"id": "u", "name": "p", "created_at": 1000, "schema_version": "v2.0"}''',
        encoding="utf-8",
    )

    from src.project.registry import GlobalRegistryStore, ProjectRegistryEntry
    GlobalRegistryStore.upsert(ProjectRegistryEntry(
        id="u", name="p", path=str(project_root),
        last_opened=1000, schema_version="v2.0",
    ))
    return project_root


def _last_task(project_id=None):
    """Find the most recently enqueued task in the default service's backend."""
    service = get_default_queue_service()
    snap = service.backend.snapshot()
    if not snap:
        return None
    return snap[-1]


def test_absolute_path_inside_project_is_anchored(project):
    """`/abs/path/to/kb/raw/sources/x.md` becomes `raw/sources/x.md`."""
    target = project / "raw" / "sources" / "x.md"
    result = ingest_service.enqueue_source(
        project_id="u",
        source=str(target),
    )
    assert result["status"] == "queued"
    last = _last_task()
    assert last.source == "raw/sources/x.md"
    assert last.source_type.value == "file"


def test_absolute_path_outside_project_raises(project):
    """An absolute path outside the project root raises IngestPathError."""
    import os
    import tempfile
    with tempfile.TemporaryDirectory() as other:
        outside = os.path.join(other, "evil.md")
        with pytest.raises(ingest_service.IngestPathError):
            ingest_service.enqueue_source(project_id="u", source=outside)


def test_relative_path_passes_through(project):
    """A relative path is left as-is."""
    result = ingest_service.enqueue_source(
        project_id="u",
        source="raw/sources/y.md",
    )
    assert result["status"] == "queued"
    last = _last_task()
    assert last.source == "raw/sources/y.md"


def test_url_passes_through(project):
    """URLs are not absolute paths; pass through unchanged."""
    result = ingest_service.enqueue_source(
        project_id="u",
        source="https://example.com/paper.pdf",
    )
    assert result["status"] == "queued"
    last = _last_task()
    assert last.source == "https://example.com/paper.pdf"


def test_absolute_path_via_symlink_anchors(tmp_path, monkeypatch):
    """If the project root is a symlink, the caller may supply a path
    through the real path or the symlink -- both should anchor to the
    project root. Uses .resolve() before .relative_to() so symlinks
    collapse to the same canonical root.
    """
    import os

    # Set up: project_root is a symlink to a real dir.
    real_root = tmp_path / "real_kb"
    real_root.mkdir()
    link_root = tmp_path / "link_kb"
    os.symlink(str(real_root), str(link_root))

    from src.project import paths as project_paths
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    monkeypatch.setattr(project_paths, "_OVERRIDE_CONFIG_DIR", cfg_dir)

    (link_root / ".llm-wiki").mkdir()
    (link_root / ".llm-wiki" / "project.json").write_text(
        '''{"id": "sym", "name": "s", "created_at": 1000, "schema_version": "v2.0"}''',
        encoding="utf-8",
    )

    from src.project.registry import GlobalRegistryStore, ProjectRegistryEntry
    GlobalRegistryStore.upsert(ProjectRegistryEntry(
        id="sym", name="s", path=str(link_root),
        last_opened=1000, schema_version="v2.0",
    ))

    # Caller supplies the REAL path (not the symlinked one). Use a
    # unique source name so the idempotency hash does not collide
    # with other tests in this file.
    target = real_root / "raw" / "sources" / "symlink_x.md"
    target.parent.mkdir(parents=True)
    target.write_text("x", encoding="utf-8")

    result = ingest_service.enqueue_source(
        project_id="sym",
        source=str(target),
    )
    assert result["status"] == "queued"
    last = _last_task()
    assert last.source == "raw/sources/symlink_x.md", (
        f"absolute path through real dir should still anchor via symlink "
        f"resolution; got source={last.source!r}"
    )


# --- auto-prefix raw/sources/ (Bug 1 fix) ---

def test_relative_path_without_prefix_auto_resolves_when_file_exists(project):
    """A relative path like '01_newbie/xxx.md' (omitting raw/sources/)
    should auto-resolve to 'raw/sources/01_newbie/xxx.md' when the file
    exists under that directory."""
    target = project / "raw" / "sources" / "01_newbie" / "xxx.md"
    target.parent.mkdir(parents=True)
    target.write_text("content", encoding="utf-8")
    result = ingest_service.enqueue_source(
        project_id="u",
        source="01_newbie/xxx.md",
    )
    assert result["status"] == "queued"
    last = _last_task()
    assert last.source == "raw/sources/01_newbie/xxx.md"


def test_relative_path_without_prefix_passes_through_when_file_not_exists(project):
    """When the file doesn't exist under raw/sources/, the path is returned
    as-is so the Collector can produce a clear PermissionDenied error."""
    result = ingest_service.enqueue_source(
        project_id="u",
        source="nonexistent.md",
    )
    assert result["status"] == "queued"
    last = _last_task()
    assert last.source == "nonexistent.md"


def test_correctly_prefixed_path_still_works(project):
    """Non-regression: a path with 'raw/sources/' prefix already present
    must still be accepted and passed through unchanged."""
    target = project / "raw" / "sources" / "exists.md"
    target.parent.mkdir(parents=True)
    target.write_text("content", encoding="utf-8")
    result = ingest_service.enqueue_source(
        project_id="u",
        source="raw/sources/exists.md",
    )
    assert result["status"] == "queued"
    last = _last_task()
    assert last.source == "raw/sources/exists.md"


def test_path_traversal_under_raw_sources_is_rejected(project):
    """'../../outside.md' should not fabricate a raw/sources/ prefix;
    it must be returned unchanged so the Collector rejects it."""
    result = ingest_service.enqueue_source(
        project_id="u",
        source="../../outside.md",
    )
    assert result["status"] == "queued"
    last = _last_task()
    # Should NOT be auto-prefixed — the file is outside raw/sources/
    assert last.source == "../../outside.md"


def test_nested_subdirectory_is_auto_prefixed(project):
    """A deeply nested relative path under raw/sources/ is auto-prefixed."""
    target = project / "raw" / "sources" / "chapter1" / "section2" / "doc.md"
    target.parent.mkdir(parents=True)
    target.write_text("content", encoding="utf-8")
    result = ingest_service.enqueue_source(
        project_id="u",
        source="chapter1/section2/doc.md",
    )
    assert result["status"] == "queued"
    last = _last_task()
    assert last.source == "raw/sources/chapter1/section2/doc.md"
