"""R13 — single version source (no API/health drift).

Audit: pyproject/__init__ say 2.0.0 but the FastAPI app and /health
hard-coded 0.2.0, so the version could not be used as a diagnostic.
R13 makes `src.__version__` the single source; app + health derive from it.
"""
from fastapi.testclient import TestClient

from src import __version__
from src.server.app import create_app

app = create_app()
client = TestClient(app)


def test_src_version_matches_pyproject():
    """src.__version__ equals the pyproject version."""
    from pathlib import Path
    import tomllib
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert __version__ == data["project"]["version"]


def test_health_version_matches_src_version():
    """/health reports the src package version."""
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["version"] == __version__


def test_app_version_matches_src_version():
    """The FastAPI app exposes the src package version."""
    assert app.version == __version__


def test_ready_uses_same_version():
    """/ready does not drift either."""
    r = client.get("/ready")
    assert r.status_code in (200, 503)
    body = r.json()
    assert body["ok"] in (True, False)


def test_provider_probe_awaits_async_close(monkeypatch):
    import src.server.ready as ready_module
    from src.llm.registry import ProviderRegistry

    closed = {"value": False}

    class Provider:
        async def health_check(self):
            return {"ok": True, "detail": "test"}

        async def close(self):
            closed["value"] = True

    monkeypatch.setattr(
        ProviderRegistry,
        "get_default",
        staticmethod(lambda: type("Default", (), {"name": "test"})()),
    )
    monkeypatch.setattr(
        "src.llm.provider_factory._create_from_config",
        lambda _config: Provider(),
    )
    monkeypatch.setitem(ready_module._provider_probe_cache, "ts", 0)

    assert ready_module.check_provider()[0] == "ok"
    assert closed["value"] is True
