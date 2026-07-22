"""Tests for src/server/routes/ — 8 FastAPI routers.

Behavioral tests using FastAPI's ``TestClient`` (200 response + correct shape).
A small number of import-smoke tests are kept as a regression layer.
"""
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.server.app import create_app
from src.server.routes import files as files_route
from src.schemas.migration import SchemaVersion
from src.schemas.registry import MigrationRegistry


# Module-level fixtures ---------------------------------------------------

app = create_app()
client = TestClient(app)


# 1. health ---------------------------------------------------------------

def test_health_returns_expected_shape():
    """GET /health returns 200 with ok/status/version/agent keys."""
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["status"] == "running"
    assert "version" in body
    assert "agent" in body
    assert isinstance(body["agent"], dict)


# 2. projects -------------------------------------------------------------

def test_projects_list_with_empty_registry(monkeypatch, tmp_path):
    """GET /api/v1/projects returns 200 + {projects: []} when registry is empty."""
    # Redirect registry to a fresh tmp dir so no other test can pollute us.
    from src.project import paths as project_paths
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    monkeypatch.setattr(project_paths, "_OVERRIDE_CONFIG_DIR", cfg)

    r = client.get("/api/v1/projects")
    assert r.status_code == 200
    assert r.json() == {"projects": []}


# 3. files ---------------------------------------------------------------

def test_files_content_rejects_path_traversal(monkeypatch, tmp_path):
    """GET /api/v1/projects/x/files/content?path=../../etc/passwd returns 4xx."""
    # Inject a fake ProjectContext with the forward-dep ctx.paths attribute.
    project_root = tmp_path / "proj"
    (project_root / "wiki").mkdir(parents=True)
    fake_ctx = MagicMock()
    fake_ctx.path = project_root
    fake_ctx.paths = MagicMock()
    fake_ctx.paths.wiki = project_root / "wiki"
    fake_ctx.paths.sources = project_root / "wiki" / "sources"
    monkeypatch.setattr(files_route, "_resolve_ctx", lambda pid: fake_ctx)

    r = client.get("/api/v1/projects/x/files/content?path=../../etc/passwd")
    assert 400 <= r.status_code < 500
    assert "escape" in r.json()["detail"].lower() or "outside" in r.json()["detail"].lower()


def test_files_content_rejects_directory(monkeypatch, tmp_path):
    """GET .../files/content?path=<dir> returns 400."""
    project_root = tmp_path / "proj"
    (project_root / "wiki" / "subdir").mkdir(parents=True)
    fake_ctx = MagicMock()
    fake_ctx.path = project_root
    fake_ctx.paths = MagicMock()
    fake_ctx.paths.wiki = project_root / "wiki"
    fake_ctx.paths.sources = project_root / "wiki" / "sources"
    monkeypatch.setattr(files_route, "_resolve_ctx", lambda pid: fake_ctx)

    r = client.get("/api/v1/projects/x/files/content?path=subdir")
    assert r.status_code == 400
    assert "directory" in r.json()["detail"].lower()


# 4. schema --------------------------------------------------------------

def test_schema_endpoint_returns_list(monkeypatch, tmp_path):
    """GET /api/v1/projects/<id>/schema returns 200 + {schemas: [...]} deterministically."""
    # Empty registry, then register one project with schema_version=v1.0
    from src.project import paths as project_paths
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    monkeypatch.setattr(project_paths, "_OVERRIDE_CONFIG_DIR", cfg)

    MigrationRegistry._clear()
    try:
        # Register a stub migration so the list is non-empty.
        class _Stub:
            schema_name = "wiki_page"
            from_version = SchemaVersion.V1_0
            to_version = SchemaVersion.V2_0
            def preview(self, ctx): pass
            def up(self, ctx): pass
            def down(self, ctx): pass
        MigrationRegistry.register("wiki_page", SchemaVersion.V1_0, SchemaVersion.V2_0, _Stub())

        from src.project.registry import GlobalRegistryStore, ProjectRegistryEntry
        import time
        GlobalRegistryStore.upsert(ProjectRegistryEntry(
            id="proj-1",
            path=str(tmp_path / "proj-root"),
            name="proj-1",
            last_opened=int(time.time() * 1000),
            schema_version="v1.0",
        ))

        # Hit the endpoint twice — response must be identical (deterministic).
        r1 = client.get("/api/v1/projects/proj-1/schema")
        r2 = client.get("/api/v1/projects/proj-1/schema")
        assert r1.status_code == 200
        assert r1.status_code == r2.status_code
        body1 = r1.json()
        body2 = r2.json()
        assert body1 == body2
        assert body1["project_id"] == "proj-1"
        assert "schemas" in body1
        for entry in body1["schemas"]:
            assert "from" in entry
            assert "to" in entry
    finally:
        MigrationRegistry._clear()


def test_schema_endpoint_unknown_project_returns_empty_schemas(monkeypatch, tmp_path):
    """GET schema for unknown project_id returns 200 with empty list (no leak)."""
    from src.project import paths as project_paths
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    monkeypatch.setattr(project_paths, "_OVERRIDE_CONFIG_DIR", cfg)

    MigrationRegistry._clear()
    try:
        r = client.get("/api/v1/projects/does-not-exist/schema")
        assert r.status_code == 200
        body = r.json()
        assert body["project_id"] == "does-not-exist"
        assert body["schemas"] == []
    finally:
        MigrationRegistry._clear()


# Import smoke layer (kept small) ----------------------------------------

def test_routes_import_smoke():
    """All 8 route modules importable and expose a router."""
    from src.server.routes import (
        health, projects, files, search, ingest, reviews, chat, schema,
    )
    for mod in (health, projects, files, search, ingest, reviews, chat, schema):
        assert getattr(mod, "router", None) is not None


# Router mount coverage ---------------------------------------------------

def _all_paths(app):
    """Recursively collect all paths from app and included routers."""
    paths = []
    for r in app.routes:
        # _IncludedRouter exposes original_router with .routes
        orig = getattr(r, "original_router", None)
        if orig is not None:
            paths.extend(_all_paths(orig))
            continue
        p = getattr(r, "path", None)
        if p:
            paths.append(p)
    return paths


def test_all_routers_mounted():
    paths = _all_paths(app)
    # health
    assert "/health" in paths
    # projects
    assert "/api/v1/projects" in paths
    # Files/Search/Ingest/Reviews/Chat/Schema are mounted under /projects/{project_id}
    assert any(p.endswith("/api/v1/projects/{project_id}/files") for p in paths)
    assert any(p.endswith("/api/v1/projects/{project_id}/files/content") for p in paths)
    assert any(p.endswith("/api/v1/projects/{project_id}/search") for p in paths)
    assert any(p.endswith("/api/v1/projects/{project_id}/ingest") for p in paths)
    assert any(p.endswith("/api/v1/projects/{project_id}/reviews") for p in paths)
    assert any(p.endswith("/api/v1/projects/{project_id}/reviews/{review_id}") for p in paths)
    assert any(p.endswith("/api/v1/projects/{project_id}/chat") for p in paths)
    assert any(p.endswith("/api/v1/projects/{project_id}/schema") for p in paths)
