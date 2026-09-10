from fastapi.testclient import TestClient

from src.server.app import create_app


def test_status_summary_route_returns_service_payload(monkeypatch):
    from src.services import status_summary

    expected = {
        "project": {"id": "p-1", "name": "Demo"},
        "status": "empty",
        "counts": {"sources": 0, "raw": {}, "kc": {}, "wiki": {}, "book": {}},
        "pending_wiki_commits": 0,
        "build_runs": 0,
        "sources": [],
    }
    monkeypatch.setattr(status_summary, "get_status_summary", lambda _project_id: expected)

    response = TestClient(create_app()).get("/api/v1/projects/p-1/status-summary")

    assert response.status_code == 200
    assert response.json() == expected

