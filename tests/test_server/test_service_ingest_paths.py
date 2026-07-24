"""Regression: services.ingest.enqueue_source normalizes absolute file paths.

Before this fix, an absolute file path like `/abs/project/raw/sources/foo.md`
was passed through verbatim, and Collector's permission check (which only
matches relative paths like `raw/sources`) raised PermissionError.
After this fix, the service anchors absolute paths to the project root
and rejects paths outside the project.
"""
import pytest

from src.services import ingest as ingest_service
from src.queue import queue as queue_module


@pytest.fixture(autouse=True)
def _reset_queue():
    """Clear the module-level _queue so tasks from this test do not leak
    into later tests (e.g. tests/test_e2e/test_ingest_happy_path.py
    which drives _process_next on whatever is at the head of the queue).
    """
    queue_module.__reset_for_testing()
    yield
    queue_module.__reset_for_testing()


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
        '{"id": "u", "name": "p", "created_at": 1000, "schema_version": "v2.0"}',
        encoding="utf-8",
    )

    from src.project.registry import GlobalRegistryStore, ProjectRegistryEntry
    GlobalRegistryStore.upsert(ProjectRegistryEntry(
        id="u", name="p", path=str(project_root),
        last_opened=1000, schema_version="v2.0",
    ))
    return project_root


def test_absolute_path_inside_project_is_anchored(project):
    """`/abs/path/to/kb/raw/sources/x.md` becomes `raw/sources/x.md`."""
    target = project / "raw" / "sources" / "x.md"
    result = ingest_service.enqueue_source(
        project_id="u",
        source=str(target),
    )
    assert result["status"] == "queued"
    # Task queued with the relative path
    last = list(queue_module._queue)[-1]
    assert last.source == "raw/sources/x.md"
    assert last.source_type.value == "file"


def test_absolute_path_outside_project_raises(project):
    """An absolute path outside the project root raises IngestPathError."""
    import os, tempfile
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
    last = list(queue_module._queue)[-1]
    assert last.source == "raw/sources/y.md"


def test_url_passes_through(project):
    """URLs are not absolute paths; pass through unchanged."""
    result = ingest_service.enqueue_source(
        project_id="u",
        source="https://example.com/paper.pdf",
    )
    assert result["status"] == "queued"
    last = list(queue_module._queue)[-1]
    assert last.source == "https://example.com/paper.pdf"
