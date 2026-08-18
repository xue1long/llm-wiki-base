"""Tests for R1 — HTTP management-surface auth + API key redaction.

Coverage:
- Provider responses never contain the raw API key.
- When a bearer token is configured, /api/v1 write ops + provider
  management require `Authorization: Bearer <token>`; /health stays
  anonymous.
- Without a token, the API behaves exactly as before (loopback default).
- Non-loopback binds are refused at CLI level unless a token exists.
"""
import json
import secrets

import pytest
from fastapi.testclient import TestClient

from src.server.app import create_app


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_app_with_token(tmp_path, monkeypatch, token: str | None):
    """Point auth at a tmp config dir and set the token (or None)."""
    from src.project import paths as project_paths
    cfg = tmp_path / "cfg"
    cfg.mkdir(exist_ok=True)
    monkeypatch.setattr(project_paths, "_OVERRIDE_CONFIG_DIR", cfg)

    import src.server.auth as auth_mod
    if token is None:
        monkeypatch.setattr(auth_mod, "get_token", lambda: None)
    else:
        monkeypatch.setattr(auth_mod, "get_token", lambda: token)
    return TestClient(create_app())


# ---------------------------------------------------------------------------
# 1. Provider responses never leak raw keys
# ---------------------------------------------------------------------------

def test_provider_get_redacts_api_key(monkeypatch, tmp_path):
    """GET /api/v1/providers/{name} never returns the raw api_key."""
    from src.llm.registry import ProviderRegistry
    from src.llm.types import ProviderConfig

    monkeypatch.setattr(
        ProviderRegistry, "require",
        lambda name: ProviderConfig(
            name=name, type="openai", base_url="https://x", api_key="sk-RAW-SECRET",
        ),
    )
    client = _make_app_with_token(tmp_path, monkeypatch, None)

    r = client.get("/api/v1/providers/test")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "sk-RAW-SECRET" not in json.dumps(body)
    assert body["provider"]["api_key"] in ("", "***")


def test_provider_add_redacts_api_key(monkeypatch, tmp_path):
    """POST /api/v1/providers response never returns the raw api_key."""
    from src.llm.registry import ProviderRegistry
    from src.llm.types import ProviderConfig

    captured = {}

    def _fake_upsert(config):
        captured["config"] = config

    monkeypatch.setattr(ProviderRegistry, "upsert", _fake_upsert)
    monkeypatch.setattr(ProviderRegistry, "require", lambda name: (_ for _ in ()).throw(KeyError(name)))
    client = _make_app_with_token(tmp_path, monkeypatch, None)

    r = client.post("/api/v1/providers", json={
        "name": "p1", "type": "openai", "api_key": "sk-RAW-SECRET",
        "base_url": "https://x", "chat_model": "gpt-4o",
    })
    assert r.status_code == 200
    body = r.json()
    assert "sk-RAW-SECRET" not in json.dumps(body)
    assert body["provider"]["api_key"] in ("", "***")
    # The registry still received the real key (write path unaffected).
    assert captured["config"].api_key == "sk-RAW-SECRET"


def test_provider_list_redacts_api_keys(monkeypatch, tmp_path):
    """GET /api/v1/providers list redacts every api_key."""
    from src.llm.registry import ProviderRegistry
    from src.llm.types import ProviderConfig

    monkeypatch.setattr(
        ProviderRegistry, "load",
        lambda: {
            "a": ProviderConfig(name="a", type="openai", api_key="sk-A"),
            "b": ProviderConfig(name="b", type="ollama", api_key=""),
        },
    )
    client = _make_app_with_token(tmp_path, monkeypatch, None)

    r = client.get("/api/v1/providers")
    assert r.status_code == 200
    body = json.dumps(r.json())
    assert "sk-A" not in body
    assert "sk-RAW" not in body


# ---------------------------------------------------------------------------
# 2. Bearer-token middleware (only when a token is configured)
# ---------------------------------------------------------------------------

def test_write_without_token_returns_401(monkeypatch, tmp_path):
    """With a token configured, an unauthenticated write op → 401."""
    client = _make_app_with_token(tmp_path, monkeypatch, "tok-123")

    r = client.post("/api/v1/projects/x/upload",
                    files={"file": ("t.md", b"# x", "text/markdown")})
    assert r.status_code == 401
    assert "token" in json.dumps(r.json()).lower() or "unauthorized" in json.dumps(r.json()).lower()


def test_write_with_wrong_token_returns_401(monkeypatch, tmp_path):
    """A wrong bearer token is rejected."""
    client = _make_app_with_token(tmp_path, monkeypatch, "tok-123")

    r = client.post(
        "/api/v1/projects/x/upload",
        files={"file": ("t.md", b"# x", "text/markdown")},
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert r.status_code == 401


def test_write_with_correct_token_passes(monkeypatch, tmp_path):
    """A valid bearer token lets the write op through to the route."""
    from src.services import files as files_service
    from src.project.context import ProjectContext
    from src.wiki.core.paths import WikiPaths

    client = _make_app_with_token(tmp_path, monkeypatch, "tok-123")

    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    identity = type("I", (), {"id": "u"})()
    monkeypatch.setattr(
        files_service, "resolve_project",
        lambda pid, by_id_only=True: (
            ProjectContext(identity=identity, path=project_dir, name="p", schema_version="v2.0"),
            WikiPaths(project_dir),
        ),
    )

    r = client.post(
        "/api/v1/projects/x/upload",
        files={"file": ("t.md", b"# hello", "text/markdown")},
        headers={"Authorization": "Bearer tok-123"},
    )
    assert r.status_code == 200
    assert r.json()["path"] == "raw/sources/t.md"


def test_provider_get_requires_token(monkeypatch, tmp_path):
    """Provider management (even GET) requires a token when configured."""
    client = _make_app_with_token(tmp_path, monkeypatch, "tok-123")

    r = client.get("/api/v1/providers/x")
    assert r.status_code == 401


def test_provider_get_with_token_allowed(monkeypatch, tmp_path):
    """Provider GET with a valid token is allowed (redaction still applies)."""
    from src.llm.registry import ProviderRegistry
    from src.llm.types import ProviderConfig

    monkeypatch.setattr(
        ProviderRegistry, "require",
        lambda name: ProviderConfig(name=name, type="openai", api_key="sk-X"),
    )
    client = _make_app_with_token(tmp_path, monkeypatch, "tok-123")

    r = client.get("/api/v1/providers/x", headers={"Authorization": "Bearer tok-123"})
    assert r.status_code == 200
    assert "sk-X" not in json.dumps(r.json())


def test_health_anonymous_even_with_token(monkeypatch, tmp_path):
    """/health stays anonymous even when a token is configured."""
    client = _make_app_with_token(tmp_path, monkeypatch, "tok-123")

    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True


def test_read_op_anonymous_with_token(monkeypatch, tmp_path):
    """Read-only /api/v1 ops (non-provider) stay anonymous with a token."""
    from src.services import wiki_analysis
    monkeypatch.setattr(wiki_analysis, "content_health", lambda project_id: {"page_count": 0})
    client = _make_app_with_token(tmp_path, monkeypatch, "tok-123")

    r = client.get("/api/v1/projects/demo/content-health")
    assert r.status_code == 200


def test_no_token_means_no_auth(monkeypatch, tmp_path):
    """Without a token, write ops behave exactly as before (no 401)."""
    from src.services import files as files_service
    from src.project.context import ProjectContext
    from src.wiki.core.paths import WikiPaths

    client = _make_app_with_token(tmp_path, monkeypatch, None)

    project_dir = tmp_path / "kb"
    project_dir.mkdir()
    identity = type("I", (), {"id": "u"})()
    monkeypatch.setattr(
        files_service, "resolve_project",
        lambda pid, by_id_only=True: (
            ProjectContext(identity=identity, path=project_dir, name="p", schema_version="v2.0"),
            WikiPaths(project_dir),
        ),
    )

    r = client.post("/api/v1/projects/x/upload",
                    files={"file": ("t.md", b"# hello", "text/markdown")})
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# 3. auth module helpers
# ---------------------------------------------------------------------------

def test_auth_token_file_roundtrip(tmp_path, monkeypatch):
    """get_token/set_token roundtrip through the config dir."""
    from src.project import paths as project_paths
    cfg = tmp_path / "cfg"
    cfg.mkdir(exist_ok=True)
    monkeypatch.setattr(project_paths, "_OVERRIDE_CONFIG_DIR", cfg)

    from src.server import auth as auth_mod

    assert auth_mod.get_token() is None
    tok = auth_mod.generate_token()
    assert len(tok) >= 32
    auth_mod.set_token(tok)
    assert auth_mod.get_token() == tok

    auth_mod.set_token("second")
    assert auth_mod.get_token() == "second"

    auth_mod.clear_token()
    assert auth_mod.get_token() is None


def test_generate_token_is_random():
    from src.server.auth import generate_token
    assert generate_token() != generate_token()


def test_is_loopback_host():
    from src.server.auth import is_loopback_host
    assert is_loopback_host("127.0.0.1")
    assert is_loopback_host("localhost")
    assert is_loopback_host("::1")
    assert is_loopback_host("")
    assert is_loopback_host("127.0.0.2")
    assert not is_loopback_host("0.0.0.0")
    assert not is_loopback_host("192.168.1.5")
    assert not is_loopback_host("10.0.0.1")


# ---------------------------------------------------------------------------
# 4. CLI: non-loopback bind refused without token
# ---------------------------------------------------------------------------

def test_serve_refuses_nonloopback_without_token(monkeypatch, tmp_path, capsys):
    """serve --host 0.0.0.0 without a token exits non-zero."""
    import sys
    from src.project import paths as project_paths
    cfg = tmp_path / "cfg"
    cfg.mkdir(exist_ok=True)
    monkeypatch.setattr(project_paths, "_OVERRIDE_CONFIG_DIR", cfg)

    import src.server.auth as auth_mod
    monkeypatch.setattr(auth_mod, "get_token", lambda: None)

    import src.cli_ext.serve as serve_mod
    monkeypatch.setattr(serve_mod, "_serve_foreground", lambda args: (_ for _ in ()).throw(AssertionError("should not start")))

    def fake_exit(code=0):
        raise SystemExit(code)
    monkeypatch.setattr(serve_mod.sys, "exit", fake_exit)

    args = type("Args", (), {"host": "0.0.0.0", "port": 9000, "daemon": False})()
    with pytest.raises(SystemExit) as exc:
        serve_mod.cmd_serve(args)
    assert exc.value.code != 0
    captured = capsys.readouterr()
    assert "token" in (captured.out + captured.err).lower()


def test_serve_allows_nonloopback_with_token(monkeypatch, tmp_path):
    """serve --host 0.0.0.0 with a token proceeds to start."""
    from src.project import paths as project_paths
    cfg = tmp_path / "cfg"
    cfg.mkdir(exist_ok=True)
    monkeypatch.setattr(project_paths, "_OVERRIDE_CONFIG_DIR", cfg)

    import src.server.auth as auth_mod
    monkeypatch.setattr(auth_mod, "get_token", lambda: "tok-123")

    import src.cli_ext.serve as serve_mod
    started = []
    monkeypatch.setattr(serve_mod, "_serve_foreground", lambda args: started.append(args.host))

    args = type("Args", (), {"host": "0.0.0.0", "port": 9000, "daemon": False})()
    serve_mod.cmd_serve(args)
    assert started == ["0.0.0.0"]


def test_serve_allows_loopback_without_token(monkeypatch, tmp_path):
    """serve --host 127.0.0.1 without a token still starts (back-compat)."""
    from src.project import paths as project_paths
    cfg = tmp_path / "cfg"
    cfg.mkdir(exist_ok=True)
    monkeypatch.setattr(project_paths, "_OVERRIDE_CONFIG_DIR", cfg)

    import src.server.auth as auth_mod
    monkeypatch.setattr(auth_mod, "get_token", lambda: None)

    import src.cli_ext.serve as serve_mod
    started = []
    monkeypatch.setattr(serve_mod, "_serve_foreground", lambda args: started.append(args.host))

    args = type("Args", (), {"host": "127.0.0.1", "port": 9000, "daemon": False})()
    serve_mod.cmd_serve(args)
    assert started == ["127.0.0.1"]
