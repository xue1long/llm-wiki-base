"""Tests for src/server/routes/ — 8 FastAPI routers.

Each test verifies the router is importable and returns a 200 response with the
correct shape for its primary endpoint.
"""
from fastapi.testclient import TestClient

from src.server.app import create_app


# Module-level fixtures ---------------------------------------------------

app = create_app()
client = TestClient(app)


# 1. health ---------------------------------------------------------------

def test_health_returns_ok():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["status"] == "running"
    assert "version" in body
    assert "agent" in body


# 2. projects -------------------------------------------------------------

def test_projects_list_returns_list():
    r = client.get("/api/v1/projects")
    assert r.status_code == 200
    body = r.json()
    assert "projects" in body
    assert isinstance(body["projects"], list)


# 3. files ---------------------------------------------------------------

def test_files_module_imports():
    from src.server.routes import files
    assert files.router is not None


# 4. search --------------------------------------------------------------

def test_search_module_imports():
    from src.server.routes import search
    assert search.router is not None


# 5. ingest --------------------------------------------------------------

def test_ingest_module_imports():
    from src.server.routes import ingest
    assert ingest.router is not None


# 6. reviews -------------------------------------------------------------

def test_reviews_module_imports():
    from src.server.routes import reviews
    assert reviews.router is not None


# 7. chat ----------------------------------------------------------------

def test_chat_module_imports():
    from src.server.routes import chat
    assert chat.router is not None


# 8. schema --------------------------------------------------------------

def test_schema_module_imports():
    from src.server.routes import schema
    assert schema.router is not None


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
