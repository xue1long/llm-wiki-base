"""Regression: IngestPathError surfaces as HTTP 400, not 500.

services/ingest.enqueue_source raises IngestPathError when an absolute
source path falls outside the registered project root. The docstring
contract is "Surfaced to the HTTP layer as a 400 Bad Request". The
route handler must translate the exception accordingly; otherwise
FastAPI's default handler returns 500.
"""
import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from src.services import ingest as ingest_service
from src.services.ingest import IngestPathError


@pytest.fixture
def client_with_project(tmp_path, monkeypatch):
    """A registered project whose root is tmp_path."""
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

    from src.server.app import create_app
    app = create_app()
    return TestClient(app)


def test_ingest_absolute_path_outside_project_returns_400(client_with_project):
    """Absolute source path outside the project root: 400 with the
    IngestPathError message in the body, not 500."""
    with tempfile.TemporaryDirectory() as other:
        outside = os.path.join(other, "evil.md")
        # Touch the file so the failure mode is IngestPathError, not FileNotFoundError.
        with open(outside, "w"):
            pass
        resp = client_with_project.post(
            "/api/v1/projects/u/ingest",
            json={"source": outside},
        )
    assert resp.status_code == 400, (
        f"IngestPathError must surface as HTTP 400; got {resp.status_code}: "
        f"{resp.text!r}"
    )
    body = resp.json()
    assert "outside project root" in body.get("detail", ""), (
        f"error body must mention the path validation failure; got: {body!r}"
    )
