from __future__ import annotations

import json
from types import SimpleNamespace

from src.integrations.gbrain.api import (
    ensure_search_config,
    get_job,
    load_search_state,
)
from src.integrations.gbrain.service import enable_search
from src.integrations.gbrain.state import load_runtime_state
from src.integrations.gbrain.types import JobStatus, SearchStatus
from src.integrations.gbrain.worker import _default_status_probe, run_search_job
from src.integrations.gbrain.worker import run_runtime_setup_job


def test_default_status_probe_reads_real_embed_coverage_field(tmp_path, monkeypatch):
    monkeypatch.setattr("src.integrations.gbrain.worker.load_runtime_config", lambda root: object())
    monkeypatch.setattr(
        "src.integrations.gbrain.worker.resolve_runtime",
        lambda root, config: SimpleNamespace(path=tmp_path / "gbrain"),
    )
    monkeypatch.setattr(
        "src.integrations.gbrain.worker.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout=json.dumps({"sources": [{"source_id": "source-a", "embed_coverage_pct": 75}]})
        ),
    )

    result = _default_status_probe(tmp_path, SimpleNamespace(source_id="source-a"))

    assert result["embedding_coverage"] == 0.75


def test_default_status_probe_fails_closed_for_invalid_coverage(tmp_path, monkeypatch):
    monkeypatch.setattr("src.integrations.gbrain.worker.load_runtime_config", lambda root: object())
    monkeypatch.setattr(
        "src.integrations.gbrain.worker.resolve_runtime",
        lambda root, config: SimpleNamespace(path=tmp_path / "gbrain"),
    )
    monkeypatch.setattr(
        "src.integrations.gbrain.worker.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout=json.dumps({"sources": [{"source_id": "source-a", "embed_coverage_pct": "invalid"}]})
        ),
    )

    result = _default_status_probe(tmp_path, SimpleNamespace(source_id="source-a"))

    assert result["embedding_coverage"] == 0.0


def test_default_status_probe_rejects_empty_source_even_with_full_ratio(tmp_path, monkeypatch):
    monkeypatch.setattr("src.integrations.gbrain.worker.load_runtime_config", lambda root: object())
    monkeypatch.setattr(
        "src.integrations.gbrain.worker.resolve_runtime",
        lambda root, config: SimpleNamespace(path=tmp_path / "gbrain"),
    )
    monkeypatch.setattr(
        "src.integrations.gbrain.worker.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout=json.dumps(
                {
                    "sources": [
                        {
                            "source_id": "source-a",
                            "total_pages": 0,
                            "total_chunks": 0,
                            "embed_coverage_pct": 100,
                        }
                    ]
                }
            )
        ),
    )

    result = _default_status_probe(tmp_path, SimpleNamespace(source_id="source-a"))

    assert result["embedding_coverage"] == 0.0


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
    state = load_search_state(tmp_path)
    assert state.status is SearchStatus.READY
    assert len(state.manifest_hash) == 64
    assert state.last_success_at > 0
    assert load_runtime_state(tmp_path)["status"] == "ready"


def test_worker_persists_runtime_failure_and_keeps_backend_local(tmp_path, monkeypatch):
    _project(tmp_path)
    monkeypatch.setattr(
        "src.integrations.gbrain.service.resolve_project_root", lambda project_id: tmp_path
    )
    ensure_search_config(tmp_path)
    job = enable_search("demo", confirm=True)

    result = run_search_job(
        tmp_path,
        job["jobId"],
        runtime_validator=lambda root: {"ready": False, "path": None, "error_code": "bun_missing"},
        importer=lambda *args: None,
        status_probe=lambda *args: {"embedding_coverage": 1.0, "path_mapping_coverage": 1.0},
    )

    assert result["error_code"] == "runtime_not_ready"
    assert load_runtime_state(tmp_path)["status"] == "failed"


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


def test_runtime_setup_job_persists_result(tmp_path, monkeypatch):
    _project(tmp_path)
    monkeypatch.setattr(
        "src.integrations.gbrain.service.resolve_project_root", lambda project_id: tmp_path
    )
    config = ensure_search_config(tmp_path)
    from src.integrations.gbrain.api import enqueue_job

    job = enqueue_job(tmp_path, "setup")
    monkeypatch.setattr(
        "src.integrations.gbrain.worker.setup_runtime",
        lambda root, runtime_config, install: type(
            "Result", (), {"status": "ready", "error_code": "", "to_dict": lambda self: {"status": self.status, "path": str(tmp_path / "gbrain")}}
        )(),
    )

    result = run_runtime_setup_job(tmp_path, job.id)

    assert result["status"] == "ready"
    assert load_runtime_state(tmp_path)["status"] == "ready"
    assert get_job(tmp_path, job.id).status is JobStatus.SUCCEEDED
