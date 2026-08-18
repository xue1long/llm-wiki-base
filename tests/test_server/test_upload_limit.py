"""Tests for R2 — upload size cap (50 MiB default) + streamed reads.

Coverage:
- Settings exposes RUFLO_MAX_UPLOAD_BYTES (default 50 MiB).
- services.files.upload_file rejects oversized content (FileTooLargeError).
- The HTTP upload route reads in chunks and returns 413 before the
  target file is written when the cap is exceeded.
- The Collector unified source-read layer enforces the cap for local
  files and URL responses (plan-audit hardening: URL/CLI/folder ingests
  cannot bypass the resource limit).
"""
import pytest
from fastapi.testclient import TestClient

from src.server.app import create_app

app = create_app()
client = TestClient(app)


# ---------------------------------------------------------------------------
# 1. Settings
# ---------------------------------------------------------------------------

def test_settings_max_upload_bytes_default():
    """RUFLO_MAX_UPLOAD_BYTES defaults to 50 MiB."""
    from src.config import settings
    assert settings().max_upload_bytes == 50 * 1024 * 1024


def test_settings_max_upload_bytes_env(monkeypatch):
    """RUFLO_MAX_UPLOAD_BYTES is read from the environment."""
    monkeypatch.setenv("RUFLO_MAX_UPLOAD_BYTES", "1024")
    from src.config import settings
    assert settings().max_upload_bytes == 1024


# ---------------------------------------------------------------------------
# 2. services.files.upload_file defensive check
# ---------------------------------------------------------------------------

def _fake_resolve(project_dir):
    from src.project.context import ProjectContext
    from src.wiki.core.paths import WikiPaths
    identity = type("I", (), {"id": "u"})()
    return (
        ProjectContext(identity=identity, path=project_dir, name="p", schema_version="v2.0"),
        WikiPaths(project_dir),
    )


def test_upload_file_rejects_oversized(monkeypatch, tmp_path):
    """upload_file raises FileTooLargeError when content exceeds the cap."""
    from src.services import files as files_service

    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    monkeypatch.setattr(
        "src.services.files.resolve_project",
        lambda project_id, by_id_only=True: _fake_resolve(project_dir),
    )
    monkeypatch.setenv("RUFLO_MAX_UPLOAD_BYTES", "100")

    with pytest.raises(files_service.FileTooLargeError):
        files_service.upload_file("u", "big.pdf", b"x" * 200)
    # Nothing written when rejected.
    assert not (project_dir / "raw" / "sources" / "big.pdf").exists()


def test_upload_file_accepts_within_cap(monkeypatch, tmp_path):
    """upload_file succeeds for content at or below the cap."""
    from src.services import files as files_service

    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    monkeypatch.setattr(
        "src.services.files.resolve_project",
        lambda project_id, by_id_only=True: _fake_resolve(project_dir),
    )
    monkeypatch.setenv("RUFLO_MAX_UPLOAD_BYTES", "100")

    result = files_service.upload_file("u", "ok.pdf", b"x" * 50)
    assert result["size"] == 50
    assert (project_dir / "raw" / "sources" / "ok.pdf").exists()


# ---------------------------------------------------------------------------
# 3. HTTP upload route — chunked read + 413
# ---------------------------------------------------------------------------

def test_upload_route_413_oversized(monkeypatch, tmp_path):
    """POST upload over the cap → 413, target file absent."""
    from src.services import files as files_service
    monkeypatch.setenv("RUFLO_MAX_UPLOAD_BYTES", "100")

    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    monkeypatch.setattr(
        files_service, "resolve_project",
        lambda pid, by_id_only=True: _fake_resolve(project_dir),
    )

    r = client.post(
        "/api/v1/projects/x/upload",
        files={"file": ("big.md", b"y" * 500, "text/markdown")},
    )
    assert r.status_code == 413
    assert not (project_dir / "raw" / "sources" / "big.md").exists()


def test_upload_route_small_ok(monkeypatch, tmp_path):
    """POST upload under the cap still works."""
    from src.services import files as files_service
    monkeypatch.setenv("RUFLO_MAX_UPLOAD_BYTES", "100")

    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    monkeypatch.setattr(
        files_service, "resolve_project",
        lambda pid, by_id_only=True: _fake_resolve(project_dir),
    )

    r = client.post(
        "/api/v1/projects/x/upload",
        files={"file": ("ok.md", b"# small", "text/markdown")},
    )
    assert r.status_code == 200
    assert (project_dir / "raw" / "sources" / "ok.md").exists()


# ---------------------------------------------------------------------------
# 4. Collector unified source-read cap (URL + local file)
# ---------------------------------------------------------------------------

def test_collector_rejects_oversized_local_file(monkeypatch, tmp_path):
    """collect() refuses a local source larger than the cap."""
    from src.pipeline import collector as collector_mod
    from src.pipeline.collector import SourceType

    monkeypatch.setenv("RUFLO_MAX_UPLOAD_BYTES", "100")

    big = tmp_path / "big.md"
    big.write_bytes(b"z" * 500)
    # resolve_project_file is bypassed when the path is absolute.
    monkeypatch.setattr(collector_mod, "enforce_permission", lambda *a, **k: None)
    monkeypatch.setattr(collector_mod, "_check_url_allowlisted", lambda *a, **k: None)

    with pytest.raises(Exception) as exc:
        import asyncio
        asyncio.run(collector_mod.collect(
            "t1", str(big), SourceType.FILE,
        ))
    assert "50" in str(exc.value) or "too large" in str(exc.value).lower() or "MiB" in str(exc.value) or "limit" in str(exc.value).lower()


def test_collector_rejects_oversized_url(monkeypatch, tmp_path):
    """collect() refuses a URL whose response exceeds the cap."""
    from src.pipeline import collector as collector_mod
    from src.pipeline.collector import SourceType

    monkeypatch.setenv("RUFLO_MAX_UPLOAD_BYTES", "100")

    class _Resp:
        is_redirect = False
        text = "x" * 500
        content = text.encode("utf-8")

        def raise_for_status(self):
            pass

    monkeypatch.setattr(collector_mod.httpx, "get", lambda *a, **k: _Resp())
    monkeypatch.setattr(collector_mod, "enforce_permission", lambda *a, **k: None)
    monkeypatch.setattr(collector_mod, "_check_url_allowlisted", lambda *a, **k: None)

    with pytest.raises(Exception) as exc:
        import asyncio
        asyncio.run(collector_mod.collect(
            "t1", "https://example.com/x.md", SourceType.URL,
        ))
    assert "too large" in str(exc.value).lower() or "limit" in str(exc.value).lower() or "MiB" in str(exc.value)


def test_collector_allows_small_url(monkeypatch, tmp_path):
    """collect() still works for URLs under the cap."""
    from src.pipeline import collector as collector_mod
    from src.pipeline.collector import SourceType

    monkeypatch.setenv("RUFLO_MAX_UPLOAD_BYTES", "100000")

    class _Resp:
        is_redirect = False
        text = "hello world"
        content = text.encode("utf-8")

        def raise_for_status(self):
            pass

    monkeypatch.setattr(collector_mod.httpx, "get", lambda *a, **k: _Resp())
    monkeypatch.setattr(collector_mod, "enforce_permission", lambda *a, **k: None)
    monkeypatch.setattr(collector_mod, "_check_url_allowlisted", lambda *a, **k: None)
    # Avoid emitting real events in tests.
    monkeypatch.setattr(collector_mod.event_bus, "emit", lambda *a, **k: None)

    import asyncio
    payload = asyncio.run(collector_mod.collect(
        "t1", "https://example.com/x.md", SourceType.URL,
    ))
    assert payload.content == "hello world"
