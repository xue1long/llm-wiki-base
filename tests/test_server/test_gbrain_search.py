from __future__ import annotations

import asyncio

from src.server.routes.gbrain_search import (
    ConfirmRequest,
    SearchConfigRequest,
    disable,
    enable,
    router,
    runtime_status,
    search_config,
    update_search_config,
)


def test_enable_route_returns_accepted_job(monkeypatch):
    monkeypatch.setattr(
        "src.server.routes.gbrain_search.gbrain_service.enable_search",
        lambda project_id, confirm: {"status": "queued", "jobId": "gbj-1"},
    )

    result = asyncio.run(enable("project-1", ConfirmRequest(confirm=True)))

    assert result == {"status": "queued", "jobId": "gbj-1"}


def test_disable_route_is_local_immediately(monkeypatch):
    monkeypatch.setattr(
        "src.server.routes.gbrain_search.gbrain_service.disable_search",
        lambda project_id: {"status": "disabled", "backend": "local"},
    )

    result = asyncio.run(disable("project-1"))

    assert result["backend"] == "local"


def test_enable_route_schedules_only_queued_job(monkeypatch):
    monkeypatch.setattr(
        "src.server.routes.gbrain_search.gbrain_service.enable_search",
        lambda project_id, confirm: {"status": "queued", "jobId": "gbj-2"},
    )
    scheduled = []

    class Tasks:
        def add_task(self, *args):
            scheduled.append(args)

    asyncio.run(enable("project-1", ConfirmRequest(confirm=True), Tasks()))

    assert scheduled and scheduled[0][1:] == ("project-1", "gbj-2")


def test_runtime_status_route_delegates(monkeypatch):
    monkeypatch.setattr(
        "src.server.routes.gbrain_search.gbrain_service.get_runtime_status",
        lambda project_id: {"status": "missing"},
    )

    assert asyncio.run(runtime_status("project-1")) == {"status": "missing"}


def test_job_route_supports_gbrain_alias():
    paths = {route.path for route in router.routes}

    assert "/api/v1/projects/{project_id}/gbrain/jobs/{job_id}" in paths


def test_search_config_route_reads_project_settings(monkeypatch):
    monkeypatch.setattr(
        "src.server.routes.gbrain_search.gbrain_service.get_search_config",
        lambda project_id: {"desired": {"result_limit": 20}},
    )

    assert asyncio.run(search_config("project-1")) == {"desired": {"result_limit": 20}}


def test_search_config_update_requires_confirmation(monkeypatch):
    monkeypatch.setattr(
        "src.server.routes.gbrain_search.gbrain_service.update_search_config",
        lambda project_id, **kwargs: kwargs,
    )

    result = asyncio.run(
        update_search_config(
            "project-1",
            SearchConfigRequest(gbrain_mode="balanced", result_limit=12, confirm=True),
        )
    )

    assert result["gbrain_mode"] == "balanced"
    assert result["result_limit"] == 12
