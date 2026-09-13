from __future__ import annotations

from fastapi.testclient import TestClient

from src.server.app import create_app


def test_skill_manager_routes_are_mounted_and_keep_file_work_in_service(monkeypatch):
    from src.services import skill_manager as service

    monkeypatch.setattr(service, "list_agents", lambda: {"agents": [{"id": "codex", "exists": True}]})
    monkeypatch.setattr(service, "inspect_artifact", lambda path: {"artifact_id": "skill-a", "content_hash": "h"})
    client = TestClient(create_app())

    assert client.get("/api/v1/skill-manager/agents").json() == {
        "agents": [{"id": "codex", "exists": True}]
    }
    assert client.post("/api/v1/skill-manager/artifacts/inspect", json={"source": "demo"}).json() == {
        "artifact_id": "skill-a", "content_hash": "h"
    }


def test_mutations_require_explicit_confirmation(monkeypatch):
    from src.services import skill_manager as service

    called = False

    def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(service, "import_artifact", fail_if_called)
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/skill-manager/artifacts/import",
        json={"source": "demo", "plan_hash": "h", "confirm": False},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "CONFIRMATION_REQUIRED"
    assert called is False
