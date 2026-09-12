from __future__ import annotations

import json

from src.integrations.gbrain.api import (
    ensure_search_config,
    get_job,
    load_search_state,
)
from src.integrations.gbrain.service import enable_search
from src.integrations.gbrain.types import JobStatus, SearchStatus
from src.integrations.gbrain.worker import run_search_job


def _project(root):
    metadata = root / ".llm-wiki"
    metadata.mkdir(parents=True)
    (metadata / "project.json").write_text(
        json.dumps({"id": "11111111-1111-4111-8111-111111111111", "name": "demo"}),
        encoding="utf-8",
    )


def test_worker_marks_ready_only_after_import_and_full_coverage(tmp_path, monkeypatch):
    _project(tmp_path)
    monkeypatch.setattr(
        "src.integrations.gbrain.service.resolve_project_root", lambda project_id: tmp_path
    )
    monkeypatch.setattr(
        "src.integrations.gbrain.worker.resolve_project_root", lambda project_id: tmp_path
    )
    config = ensure_search_config(tmp_path)
    (tmp_path / "wiki" / "sources").mkdir(parents=True)
    (tmp_path / "wiki" / "sources" / "a.md").write_text("a", encoding="utf-8")
    job = enable_search("demo", confirm=True)
    calls = []

    result = run_search_job(
        tmp_path,
        job["jobId"],
        runtime_validator=lambda root: {"ready": True, "path": str(tmp_path / "gbrain")},
        importer=lambda root, cfg, runtime: calls.append((root, cfg.source_id, runtime)),
        status_probe=lambda root, cfg: {"embedding_coverage": 1.0, "path_mapping_coverage": 1.0},
    )

    assert result["status"] == "ready"
    assert calls[0][1] == config.source_id
    assert get_job(tmp_path, job["jobId"]).status is JobStatus.SUCCEEDED
    assert load_search_state(tmp_path).status is SearchStatus.READY


def test_worker_fails_closed_when_embedding_is_incomplete(tmp_path, monkeypatch):
    _project(tmp_path)
    monkeypatch.setattr(
        "src.integrations.gbrain.service.resolve_project_root", lambda project_id: tmp_path
    )
    monkeypatch.setattr(
        "src.integrations.gbrain.worker.resolve_project_root", lambda project_id: tmp_path
    )
    ensure_search_config(tmp_path)
    job = enable_search("demo", confirm=True)

    result = run_search_job(
        tmp_path,
        job["jobId"],
        runtime_validator=lambda root: {"ready": True, "path": str(tmp_path / "gbrain")},
        importer=lambda *args: None,
        status_probe=lambda root, cfg: {"embedding_coverage": 0.5, "path_mapping_coverage": 1.0},
    )

    assert result["status"] == "failed"
    assert result["error_code"] == "embedding_incomplete"
    assert get_job(tmp_path, job["jobId"]).status is JobStatus.FAILED
    assert load_search_state(tmp_path).status is SearchStatus.FAILED
