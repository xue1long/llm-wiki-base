from __future__ import annotations

import asyncio

from src.server.routes.gbrain_search import (
    ConfirmRequest,
    disable,
    enable,
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
