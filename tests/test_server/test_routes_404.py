"""C-13 regression: every route maps `ProjectNotFoundError` to HTTP 404.

The previous routes called service functions that internally invoke
`resolve_project(project_id)`. If the project did not exist, the route
re-threw the exception as a 500 (or 502), confusing clients. The fix:

- Every route handler in src/server/routes/ now wraps its service call
  in `try/except ProjectNotFoundError as e: raise HTTPException(404, str(e))`.
- The services still raise `ProjectNotFoundError` (from
  src/project/context.py) — that's the canonical error type.

This file exercises the five routes that resolve a project:
  - POST /api/v1/projects/{project_id}/ingest
  - POST /api/v1/projects/{project_id}/search
  - POST /api/v1/projects/{project_id}/chat
  - GET  /api/v1/projects/{project_id}/reviews
  - PATCH /api/v1/projects/{project_id}/reviews/{review_id}
  - GET  /api/v1/projects/{project_id}/files

Plus the pre-existing GET /api/v1/projects/{project_id} already catches
ProjectNotFound, so it's not re-tested here.
"""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.project.context import ProjectNotFoundError
from src.server.app import create_app


app = create_app()
client = TestClient(app)


def _stub_pnf(project_id: str, *args, **kwargs):
    raise ProjectNotFoundError(f"Project not found: {project_id}")


# ingest ---------------------------------------------------------------

def test_ingest_returns_404_when_project_not_found():
    """POST /projects/<missing>/ingest -> 404."""
    with patch("src.server.routes.ingest.ingest_service.enqueue_source", side_effect=_stub_pnf):
        r = client.post(
            "/api/v1/projects/does-not-exist/ingest",
            json={"source": "https://example.com/foo"},
        )
    assert r.status_code == 404
    assert "Project not found" in r.json()["detail"]


# search ---------------------------------------------------------------

def test_search_returns_404_when_project_not_found():
    """POST /projects/<missing>/search -> 404."""
    async def _async_pnf(*args, **kwargs):
        raise ProjectNotFoundError(f"Project not found")

    with patch("src.server.routes.search.search_service.search", side_effect=_async_pnf):
        r = client.post(
            "/api/v1/projects/does-not-exist/search",
            json={"query": "foo", "topK": 5, "mode": "hybrid"},
        )
    assert r.status_code == 404
    assert "Project not found" in r.json()["detail"]


# chat -----------------------------------------------------------------

def test_chat_returns_404_when_project_not_found():
    """POST /projects/<missing>/chat -> 404 (before AgentRunFailed handling)."""
    async def _async_pnf(*args, **kwargs):
        raise ProjectNotFoundError(f"Project not found")

    with patch("src.server.routes.chat.chat_service.run_chat", side_effect=_async_pnf):
        r = client.post(
            "/api/v1/projects/does-not-exist/chat",
            json={"message": "hi"},
        )
    assert r.status_code == 404
    assert "Project not found" in r.json()["detail"]


# reviews: list ---------------------------------------------------------

def test_reviews_list_returns_404_when_project_not_found():
    """GET /projects/<missing>/reviews -> 404."""
    with patch(
        "src.server.routes.reviews.reviews_service.list_reviews",
        side_effect=_stub_pnf,
    ):
        r = client.get("/api/v1/projects/does-not-exist/reviews")
    assert r.status_code == 404
    assert "Project not found" in r.json()["detail"]


# reviews: resolve ------------------------------------------------------

def test_reviews_patch_returns_404_when_project_not_found():
    """PATCH /projects/<missing>/reviews/<id> -> 404."""
    with patch(
        "src.server.routes.reviews.reviews_service.resolve_review",
        side_effect=_stub_pnf,
    ):
        r = client.patch(
            "/api/v1/projects/does-not-exist/reviews/r1",
            json={"resolved": True, "action": "skip"},
        )
    assert r.status_code == 404
    assert "Project not found" in r.json()["detail"]


# files: list -----------------------------------------------------------

def test_files_list_returns_404_when_project_not_found():
    """GET /projects/<missing>/files -> 404."""
    with patch(
        "src.server.routes.files.files_service.list_files",
        side_effect=_stub_pnf,
    ):
        r = client.get("/api/v1/projects/does-not-exist/files")
    assert r.status_code == 404
    assert "Project not found" in r.json()["detail"]


# files: content (exercises the route's other except branches) ---------

def test_files_content_returns_404_when_project_not_found():
    """GET /projects/<missing>/files/content?path=x -> 404."""
    with patch(
        "src.server.routes.files.files_service.read_file_content",
        side_effect=_stub_pnf,
    ):
        r = client.get("/api/v1/projects/does-not-exist/files/content?path=x.md")
    assert r.status_code == 404
    assert "Project not found" in r.json()["detail"]


# schema ---------------------------------------------------------------

def test_schema_get_returns_404_when_project_not_found():
    """GET /projects/<missing>/schema -> 404 (audit I7).

    The schema service raises ProjectNotFoundError when the project is not
    registered. The route catches it and maps it to HTTP 404 so unknown
    projects are not silently returned with an empty schemas list.
    """
    with patch(
        "src.server.routes.schema.schema_service.get_schema",
        side_effect=_stub_pnf,
    ):
        r = client.get("/api/v1/projects/does-not-exist/schema")
    assert r.status_code == 404
    assert "Project not found" in r.json()["detail"]