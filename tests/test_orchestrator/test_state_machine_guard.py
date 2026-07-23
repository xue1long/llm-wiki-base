from types import SimpleNamespace

import src.orchestrator.orchestrator as orchestrator_module
from src.orchestrator.state_machine import get_next_status
from src.types import TaskStatus


def test_get_next_status_returns_candidate_for_valid_transition():
    assert (
        get_next_status(TaskStatus.RUNNING, "processor:done")
        is TaskStatus.WAITING_REVIEW
    )


def test_get_next_status_rejects_event_from_invalid_source_status():
    assert get_next_status(TaskStatus.PENDING, "audit:pass") is None


def test_get_next_status_returns_none_for_unknown_event():
    assert get_next_status(TaskStatus.RUNNING, "unknown:event") is None


def test_processor_pass_handler_uses_task_status_enum(monkeypatch):
    calls = []
    monkeypatch.setattr(
        orchestrator_module,
        "run_hard_audit",
        lambda _: SimpleNamespace(passed=True, reasons=[]),
    )
    monkeypatch.setattr(
        orchestrator_module,
        "update_task_status",
        lambda *args: calls.append(args),
    )

    orchestrator_module._on_processor_done(
        SimpleNamespace(task_id="t1", note_path="note.md")
    )

    assert calls == [("t1", TaskStatus.APPROVED)]


def test_processor_fail_handler_uses_task_status_enum(monkeypatch):
    calls = []
    monkeypatch.setattr(
        orchestrator_module,
        "run_hard_audit",
        lambda _: SimpleNamespace(passed=False, reasons=["bad note"]),
    )
    monkeypatch.setattr(
        orchestrator_module,
        "update_task_status",
        lambda *args: calls.append(args),
    )

    orchestrator_module._on_processor_done(
        SimpleNamespace(task_id="t1", note_path="note.md")
    )

    assert calls == [("t1", TaskStatus.REJECTED, "bad note")]


def test_librarian_handler_uses_task_status_enum(monkeypatch):
    calls = []
    monkeypatch.setattr(
        orchestrator_module,
        "update_task_status",
        lambda *args: calls.append(args),
    )

    orchestrator_module._on_librarian_done(SimpleNamespace(task_id="t1"))

    assert calls == [("t1", TaskStatus.ARCHIVED)]
