from __future__ import annotations

import json

import pytest

from dataclasses import replace

from src.integrations.gbrain.api import load_search_config, load_search_state, save_search_state
from src.integrations.gbrain.types import SearchStatus
from src.integrations.gbrain.runtime import RuntimeConfig, RuntimeResolution, RuntimeStatus, RuntimeValidation
from src.integrations.gbrain.state import load_runtime_state
from src.integrations.gbrain.service import (
    disable_search,
    enable_search,
    get_search_status,
    rebuild_search,
    get_runtime_status,
    get_search_config,
    update_search_config,
)


def _project(root):
    metadata = root / ".llm-wiki"
    metadata.mkdir(parents=True)
    (metadata / "project.json").write_text(
        json.dumps({"id": "11111111-1111-4111-8111-111111111111", "name": "demo"}),
        encoding="utf-8",
    )


def test_enable_requires_explicit_confirmation_and_queues(tmp_path, monkeypatch):
    _project(tmp_path)
    monkeypatch.setattr(
        "src.integrations.gbrain.service.resolve_project_root",
        lambda project_id: tmp_path,
    )

    with pytest.raises(ValueError, match="confirmation_required"):
        enable_search("demo", confirm=False)

    result = enable_search("demo", confirm=True)

    assert result["status"] == "queued"
    assert result["jobId"].startswith("gbj-")
    assert load_search_config(tmp_path).enabled is True
    assert load_search_state(tmp_path).job_id == result["jobId"]


def test_disable_increments_epoch_and_immediately_returns_local(tmp_path, monkeypatch):
    _project(tmp_path)
    monkeypatch.setattr(
        "src.integrations.gbrain.service.resolve_project_root",
        lambda project_id: tmp_path,
    )
    enable_search("demo", confirm=True)
    result = disable_search("demo")

    assert result == {"status": "disabled", "backend": "local"}
    assert load_search_config(tmp_path).enabled is False
    assert load_search_config(tmp_path).config_epoch == 2
    assert load_search_state(tmp_path).status.value == "disabled"


def test_rebuild_requires_confirmation(tmp_path, monkeypatch):
    _project(tmp_path)
    monkeypatch.setattr(
        "src.integrations.gbrain.service.resolve_project_root",
        lambda project_id: tmp_path,
    )

    with pytest.raises(ValueError, match="confirmation_required"):
        rebuild_search("demo", confirm=False)


def test_enable_is_idempotent_when_already_ready(tmp_path, monkeypatch):
    _project(tmp_path)
    monkeypatch.setattr(
        "src.integrations.gbrain.service.resolve_project_root",
        lambda project_id: tmp_path,
    )
    first = enable_search("demo", confirm=True)
    save_search_state(
        tmp_path,
        replace(load_search_state(tmp_path), status=SearchStatus.READY, job_id=first["jobId"]),
    )

    assert enable_search("demo", confirm=True) == {
        "status": "ready",
        "jobId": first["jobId"],
    }


def test_runtime_status_persists_sanitized_validation(tmp_path, monkeypatch):
    _project(tmp_path)
    monkeypatch.setattr(
        "src.integrations.gbrain.service.resolve_project_root", lambda project_id: tmp_path
    )
    monkeypatch.setattr("src.integrations.gbrain.service.load_runtime_config", lambda root: RuntimeConfig())
    monkeypatch.setattr(
        "src.integrations.gbrain.service.resolve_runtime",
        lambda root, config: RuntimeResolution(RuntimeStatus.FOUND, tmp_path / "gbrain", "env"),
    )
    monkeypatch.setattr(
        "src.integrations.gbrain.service.validate_runtime",
        lambda resolution, **kwargs: RuntimeValidation(
            "ready", resolution.path, resolution.origin, "0.42.58.0", {"mcp": True}
        ),
    )

    result = get_runtime_status("demo")

    assert result["status"] == "ready"
    assert load_runtime_state(tmp_path)["path"].endswith("gbrain")


def test_runtime_status_reuses_recent_ready_validation(tmp_path, monkeypatch):
    _project(tmp_path)
    (tmp_path / "gbrain").mkdir()
    monkeypatch.setattr(
        "src.integrations.gbrain.service.resolve_project_root", lambda project_id: tmp_path
    )
    monkeypatch.setattr("src.integrations.gbrain.service.load_runtime_config", lambda root: RuntimeConfig())
    monkeypatch.setattr(
        "src.integrations.gbrain.service.resolve_runtime",
        lambda root, config: RuntimeResolution(RuntimeStatus.FOUND, tmp_path / "gbrain", "env"),
    )
    calls = []

    def validate(*args, **kwargs):
        calls.append(1)
        return RuntimeValidation("ready", tmp_path / "gbrain", "env", "0.42.58.0", {"mcp": True})

    monkeypatch.setattr("src.integrations.gbrain.service.validate_runtime", validate)

    get_runtime_status("demo")
    get_runtime_status("demo")

    assert len(calls) == 1


def test_search_config_reports_effective_mode_and_scope(tmp_path, monkeypatch):
    _project(tmp_path)
    monkeypatch.setattr(
        "src.integrations.gbrain.service.resolve_project_root", lambda project_id: tmp_path
    )
    (tmp_path / "gbrain").mkdir()
    from src.integrations.gbrain.state import save_runtime_state
    save_runtime_state(tmp_path, {"status": "ready", "path": str(tmp_path / "gbrain")})
    monkeypatch.setattr(
        "src.integrations.gbrain.service.read_search_mode", lambda path: "conservative"
    )

    result = get_search_config("demo")

    assert result["effective"]["gbrain_mode"] == "conservative"
    assert result["scope"] == "gbrain_instance"
    assert result["capabilities"]["token_budget"] is False


def test_update_search_config_applies_and_persists_verified_mode(tmp_path, monkeypatch):
    _project(tmp_path)
    monkeypatch.setattr(
        "src.integrations.gbrain.service.resolve_project_root", lambda project_id: tmp_path
    )
    (tmp_path / "gbrain").mkdir()
    from src.integrations.gbrain.state import save_runtime_state
    save_runtime_state(tmp_path, {"status": "ready", "path": str(tmp_path / "gbrain")})
    calls = []
    monkeypatch.setattr(
        "src.integrations.gbrain.service.apply_search_mode",
        lambda path, mode: calls.append((path, mode)) or {"gbrain_mode": mode},
    )
    monkeypatch.setattr(
        "src.integrations.gbrain.service.read_search_mode", lambda path: "balanced"
    )

    result = update_search_config(
        "demo", gbrain_mode="balanced", result_limit=12, confirm=True
    )

    assert calls == [(str(tmp_path / "gbrain"), "balanced")]
    assert result["desired"] == {"gbrain_mode": "balanced", "result_limit": 12}
    assert load_search_config(tmp_path).config_epoch == 2
