from __future__ import annotations

import json
import hashlib

import pytest

from src.integrations.gbrain.api import (
    GBrainProjectError,
    enqueue_job,
    ensure_search_config,
    get_job,
    load_jobs,
    load_search_config,
    load_search_state,
    save_search_state,
    update_job,
    validate_source_ownership,
)
from src.integrations.gbrain.types import JobStatus, SearchStatus


def _project(root, project_id="11111111-1111-4111-8111-111111111111"):
    metadata = root / ".llm-wiki"
    metadata.mkdir(parents=True)
    (metadata / "project.json").write_text(
        json.dumps({"id": project_id, "name": "demo", "created_at": 1}),
        encoding="utf-8",
    )


def test_search_config_is_disabled_and_source_id_is_stable(tmp_path):
    _project(tmp_path)

    first = ensure_search_config(tmp_path)
    second = ensure_search_config(tmp_path)

    assert first.enabled is False
    assert first.source_id == "ruflo-" + hashlib.sha256(
        b"11111111-1111-4111-8111-111111111111"
    ).hexdigest()[:12]
    assert first.source_id == second.source_id
    assert first.source_path == "wiki"
    assert load_search_config(tmp_path) == first


def test_source_ownership_is_fail_closed(tmp_path):
    _project(tmp_path)
    config = ensure_search_config(tmp_path)

    assert validate_source_ownership(tmp_path, config.source_id) is True
    with pytest.raises(GBrainProjectError, match="source_ownership_conflict"):
        validate_source_ownership(tmp_path, "ruflo-other")


def test_search_state_has_safe_defaults_and_is_atomic(tmp_path):
    _project(tmp_path)
    ensure_search_config(tmp_path)

    state = load_search_state(tmp_path)
    assert state.status is SearchStatus.DISABLED
    assert state.embedding_coverage == 0.0
    assert state.path_mapping_coverage == 0.0

    save_search_state(tmp_path, state.__class__(status=SearchStatus.READY, config_epoch=2))
    assert load_search_state(tmp_path).status is SearchStatus.READY
    assert not list((tmp_path / ".index" / "gbrain").glob("*.tmp"))


def test_jobs_are_deduplicated_per_kind_and_epoch(tmp_path):
    _project(tmp_path)
    ensure_search_config(tmp_path)

    first = enqueue_job(tmp_path, "enable")
    duplicate = enqueue_job(tmp_path, "enable")
    other = enqueue_job(tmp_path, "rebuild")

    assert duplicate.id == first.id
    assert other.id != first.id
    assert len(load_jobs(tmp_path)) == 2

    update_job(tmp_path, first.id, status=JobStatus.SUCCEEDED)
    replacement = enqueue_job(tmp_path, "enable")
    assert replacement.id != first.id
    assert get_job(tmp_path, replacement.id).status is JobStatus.QUEUED
