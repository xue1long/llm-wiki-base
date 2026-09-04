"""R5 — /ready readiness probe (per-component checks, 200/503).

Audit A-04: /health unconditionally returned ok:true, so a live process
with a dead queue/vector store/provider looked healthy. R5 keeps /health
as liveness and adds /ready which reports each component's state:
- queue: JSON file writable / queue service loadable
- wiki: project root writable (for the active project)
- vector: vector-store handle initialised (best-effort)
- provider: default LLM provider configured + last known health

Every component check is defensive (never raises); a failed component
returns 503 with a per-component detail map. /ready stays anonymous.
"""
from fastapi.testclient import TestClient

from src.server.app import create_app


app = create_app()
client = TestClient(app)


def _patch_all_ok(monkeypatch):
    """Force every readiness component to report healthy."""
    import src.server.ready as ready_mod
    monkeypatch.setitem(
        ready_mod._CHECK_FUNCS,
        "queue", lambda: ("ok", "queue ok"),
    )
    monkeypatch.setitem(
        ready_mod._CHECK_FUNCS,
        "wiki", lambda: ("ok", "wiki ok"),
    )
    monkeypatch.setitem(
        ready_mod._CHECK_FUNCS,
        "vector", lambda: ("ok", "vector ok"),
    )
    monkeypatch.setitem(
        ready_mod._CHECK_FUNCS,
        "provider", lambda: ("ok", "provider ok"),
    )
    return ready_mod


def test_health_still_anonymous_liveness(monkeypatch):
    """/health remains a liveness endpoint (no component checks)."""
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_ready_200_when_all_ok(monkeypatch):
    """All components healthy → 200 with ok:true and per-component map."""
    _patch_all_ok(monkeypatch)
    r = client.get("/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["checks"]["queue"]["status"] == "ok"
    assert body["checks"]["wiki"]["status"] == "ok"
    assert body["checks"]["vector"]["status"] == "ok"
    assert body["checks"]["provider"]["status"] == "ok"


def test_ready_503_when_queue_down(monkeypatch):
    """A failed queue component → 503, other components still reported."""
    import src.server.ready as ready_mod
    monkeypatch.setitem(ready_mod._CHECK_FUNCS, "queue", lambda: ("error", "queue file unwritable"))
    monkeypatch.setitem(ready_mod._CHECK_FUNCS, "wiki", lambda: ("ok", "wiki ok"))
    monkeypatch.setitem(ready_mod._CHECK_FUNCS, "vector", lambda: ("ok", "vector ok"))
    monkeypatch.setitem(ready_mod._CHECK_FUNCS, "provider", lambda: ("ok", "provider ok"))

    r = client.get("/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["ok"] is False
    assert body["checks"]["queue"]["status"] == "error"
    assert "queue file unwritable" in body["checks"]["queue"]["detail"]


def test_ready_503_when_provider_missing(monkeypatch):
    """No default provider configured → 503 with a clear provider entry."""
    import src.server.ready as ready_mod
    monkeypatch.setitem(ready_mod._CHECK_FUNCS, "queue", lambda: ("ok", "queue ok"))
    monkeypatch.setitem(ready_mod._CHECK_FUNCS, "wiki", lambda: ("ok", "wiki ok"))
    monkeypatch.setitem(ready_mod._CHECK_FUNCS, "vector", lambda: ("ok", "vector ok"))
    monkeypatch.setitem(ready_mod._CHECK_FUNCS, "provider", lambda: ("error", "no default provider"))

    r = client.get("/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["checks"]["provider"]["status"] == "error"
    assert "no default provider" in body["checks"]["provider"]["detail"]


def test_ready_is_anonymous_with_token(monkeypatch, tmp_path):
    """/ready is reachable without a bearer token even when auth is on."""
    from src.project import paths as project_paths
    cfg = tmp_path / "cfg"
    cfg.mkdir(exist_ok=True)
    monkeypatch.setattr(project_paths, "_OVERRIDE_CONFIG_DIR", cfg)

    import src.server.auth as auth_mod
    monkeypatch.setattr(auth_mod, "get_token", lambda: "tok-123")
    _patch_all_ok(monkeypatch)

    c2 = TestClient(create_app())
    r = c2.get("/ready")
    assert r.status_code == 200
