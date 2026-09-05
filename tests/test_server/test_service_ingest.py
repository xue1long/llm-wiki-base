"""Tests for src.services.ingest — source enqueue with idempotency."""
import pytest

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

    # Audit I5: ingest service now passes project_id through to enqueue_task.
    monkeypatch.setattr(ingest_service, "enqueue_task", lambda source, stype, thash, project_id=None, **kw: "task-123")

    result = ingest_service.enqueue_source("u", "https://example.com/page")
    assert result["status"] == "queued"
    assert result["taskId"] == "task-123"
    assert result["reason"] is None


def test_enqueue_url_registers_lineage_source(monkeypatch, tmp_path):
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    _stub_resolve(monkeypatch, project_dir)
    monkeypatch.setattr(
        ingest_service, "enqueue_task",
        lambda source, stype, thash, project_id=None, **kw: "task-url",
    )

    result = ingest_service.enqueue_source("u", "https://example.com/page")

    assert result["sourceId"].startswith("src-")
    from src.lineage import LineageStore
    source = LineageStore.open(project_dir).source(result["sourceId"])
    assert source["source_path"] == "https://example.com/page"


def test_enqueue_file_source_detected(monkeypatch, tmp_path):
    """A non-URL string source is treated as SourceType.FILE."""
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    _stub_resolve(monkeypatch, project_dir)

    captured = {}
    def fake_enqueue(source, stype, thash, project_id=None, **kw):
        captured["source"] = source
        captured["stype"] = stype
        return "task-456"
    monkeypatch.setattr(ingest_service, "enqueue_task", fake_enqueue)

    result = ingest_service.enqueue_source("u", "raw/sources/input.md")
    assert result["status"] == "queued"
    assert captured["stype"] == "file"


def test_enqueue_existing_file_registers_lineage_before_queue(monkeypatch, tmp_path):
    project_dir = tmp_path / "kb"
    source = project_dir / "raw" / "sources" / "input.md"
    source.parent.mkdir(parents=True)
    source.write_text("content", encoding="utf-8")
    _stub_resolve(monkeypatch, project_dir)
    def fake_enqueue(*args, **kwargs):
        from src.lineage.api import LineageStore
        store = LineageStore.open(project_dir)
        assert store._db.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 1
        return "task-lineage"
    monkeypatch.setattr(ingest_service, "enqueue_task", fake_enqueue)

    result = ingest_service.enqueue_source("u", "raw/sources/input.md")
    assert result["taskId"] == "task-lineage"
    assert result["sourceId"].startswith("src-")


def test_enqueue_existing_unsupported_file_is_blocked(monkeypatch, tmp_path):
    project_dir = tmp_path / "kb"
    source = project_dir / "raw" / "sources" / "input.bin"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"content")
    _stub_resolve(monkeypatch, project_dir)
    monkeypatch.setattr(ingest_service, "enqueue_task", lambda *args, **kwargs: pytest.fail("must not enqueue"))

    result = ingest_service.enqueue_source("u", "raw/sources/input.bin")
    assert result["status"] == "blocked"
    assert result["reason"] == "unsupported_format"


def test_enqueue_external_absolute_file_is_rejected(monkeypatch, tmp_path):
    """Absolute files outside the project must not bypass the collector boundary."""
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    _stub_resolve(monkeypatch, project_dir)

    import pytest

    with pytest.raises(ingest_service.IngestPathError):
        ingest_service.enqueue_source("u", "C:/outside/input.md")


def test_enqueue_folder_source(monkeypatch, tmp_path):
    """A dict source {"folder": "..."} is treated as SourceType.FILE."""
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    # Create the folder under project root so the existence check passes.
    docs_dir = project_dir / "data" / "docs"
    docs_dir.mkdir(parents=True)
    (docs_dir / "test.md").write_text("# Test", encoding="utf-8")
    _stub_resolve(monkeypatch, project_dir)

    captured = {}
    def fake_enqueue_batch(items, project_id=None, **kw):
        captured["items"] = items
        return ["task-789"]
    monkeypatch.setattr(ingest_service, "enqueue_batch", fake_enqueue_batch)
    monkeypatch.setattr(ingest_service, "enqueue_task", lambda source, stype, thash, project_id=None, **kw: "task-789")
    # Stub the queue service advance() to avoid triggering pipeline handlers.
    monkeypatch.setattr(
        ingest_service, "get_default_queue_service",
        lambda: type("StubQS", (), {"advance": lambda self, project_id=None: None})(),
    )

    result = ingest_service.enqueue_source("u", {"folder": "data/docs"})
    assert result["status"] == "batch_queued"
    assert len(captured["items"]) == 1
    assert captured["items"][0]["source"] == "data/docs/test.md"


def test_enqueue_duplicate_returns_ignored(monkeypatch, tmp_path):
    """enqueue_task returning empty string indicates duplicate (idempotency hit)."""
    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    _stub_resolve(monkeypatch, project_dir)

    monkeypatch.setattr(ingest_service, "enqueue_task", lambda source, stype, thash, project_id=None, **kw: "")

    result = ingest_service.enqueue_source("u", "https://example.com/dup")
    assert result["status"] == "ignored"
    assert result["taskId"] is None
    assert result["reason"] == "Duplicate"
