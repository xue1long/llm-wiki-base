from __future__ import annotations

import json

import pytest

from dataclasses import replace

from src.integrations.gbrain.api import load_search_config, load_search_state, save_search_state
from src.integrations.gbrain.types import SearchStatus
from src.integrations.gbrain.service import (
    disable_search,
    enable_search,
    get_search_status,
    rebuild_search,
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
