"""Tests for src.services.ingest — source enqueue with idempotency."""
from src.services import ingest as ingest_service


def _stub_resolve(monkeypatch, project_dir):
    """Stub resolve_project to skip the real ProjectContext.resolve path."""
    monkeypatch.setattr(
        "src.services.ingest.resolve_project",
        lambda project_id, by_id_only=True: _fake_resolve(project_dir),
    )


def _fake_resolve(project_dir):
    from src.project.context import ProjectContext
    from src.wiki.core.paths import WikiPaths
    identity = type("I", (), {"id": "u"})()
    ctx = ProjectContext(identity=identity, path=project_dir, name="p", schema_version="v2.0")
    return ctx, WikiPaths(project_dir)


def test_enqueue_url_source(monkeypatch, tmp_path):
    """A URL source is enqueued as SourceType.URL with a generated hash."""
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    _stub_resolve(monkeypatch, project_dir)

    from src.queue import queue as q
    # Audit I5: ingest service now passes project_id through to enqueue_task.
    monkeypatch.setattr(ingest_service, "enqueue_task", lambda source, stype, thash, project_id=None: "task-123")

    result = ingest_service.enqueue_source("u", "https://example.com/page")
    assert result["status"] == "queued"
    assert result["taskId"] == "task-123"
    assert result["reason"] is None


def test_enqueue_file_source_detected(monkeypatch, tmp_path):
    """A non-URL string source is treated as SourceType.FILE."""
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    _stub_resolve(monkeypatch, project_dir)

    from src.queue import queue as q
    captured = {}
    def fake_enqueue(source, stype, thash, project_id=None):
        captured["source"] = source
        captured["stype"] = stype
        return "task-456"
    monkeypatch.setattr(ingest_service, "enqueue_task", fake_enqueue)

    result = ingest_service.enqueue_source("u", "/some/file/path.md")
    assert result["status"] == "queued"
    assert captured["stype"] == "file"


def test_enqueue_folder_source(monkeypatch, tmp_path):
    """A dict source {"folder": "..."} is treated as SourceType.FILE."""
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    _stub_resolve(monkeypatch, project_dir)

    from src.queue import queue as q
    captured = {}
    def fake_enqueue(source, stype, thash, project_id=None):
        captured["source"] = source
        return "task-789"
    monkeypatch.setattr(ingest_service, "enqueue_task", fake_enqueue)

    result = ingest_service.enqueue_source("u", {"folder": "/data/docs"})
    assert result["status"] == "queued"
    assert captured["source"] == "/data/docs"


def test_enqueue_duplicate_returns_ignored(monkeypatch, tmp_path):
    """enqueue_task returning empty string indicates duplicate (idempotency hit)."""
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    _stub_resolve(monkeypatch, project_dir)

    from src.queue import queue as q
    monkeypatch.setattr(ingest_service, "enqueue_task", lambda source, stype, thash, project_id=None: "")

    result = ingest_service.enqueue_source("u", "https://example.com/dup")
    assert result["status"] == "ignored"
    assert result["taskId"] is None
    assert result["reason"] == "Duplicate"
