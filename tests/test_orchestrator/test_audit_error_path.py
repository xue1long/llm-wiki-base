"""Tests for I-orch-4 fix: _on_processor_done must catch exceptions from
run_hard_audit and surface them as REJECTED with the error string.

Before T8, an exception raised by run_hard_audit (e.g. corrupt YAML, OS
error reading the note path) propagated up through the EventBus and was
silently logged; the task stayed in WAITING_REVIEW forever. T8 wraps the
audit in try/except and explicitly calls
`update_task_status(task_id, REJECTED, error=str(e))` on failure.
"""
from types import SimpleNamespace

import src.orchestrator.orchestrator as orchestrator_module
from src.types import TaskStatus


def test_audit_exception_marks_task_rejected(monkeypatch):
    """run_hard_audit raises -> task is marked REJECTED with the error string."""
    calls = []

    def boom(_):
        raise RuntimeError("audit crashed")

    monkeypatch.setattr(orchestrator_module, "run_hard_audit", boom)
    monkeypatch.setattr(
        orchestrator_module,
        "update_task_status",
        lambda *args: calls.append(args),
    )

    # Must NOT raise; the handler absorbs the audit exception.
    orchestrator_module._on_processor_done(
        SimpleNamespace(task_id="t1", note_path="note.md")
    )

    assert calls == [("t1", TaskStatus.REJECTED, "audit crashed")]


def test_audit_value_error_includes_str(monkeypatch):
    """A ValueError's str() is what gets recorded as the task error."""
    calls = []

    monkeypatch.setattr(
        orchestrator_module,
        "run_hard_audit",
        lambda _: (_ for _ in ()).throw(ValueError("malformed frontmatter")),
    )
    monkeypatch.setattr(
        orchestrator_module,
        "update_task_status",
        lambda *args: calls.append(args),
    )

    orchestrator_module._on_processor_done(
        SimpleNamespace(task_id="t2", note_path="note.md")
    )

    assert calls == [("t2", TaskStatus.REJECTED, "malformed frontmatter")]


def test_audit_pass_path_unchanged(monkeypatch):
    """Regression: when run_hard_audit returns passed=True, behaviour is unchanged."""
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
        SimpleNamespace(task_id="t3", note_path="note.md")
    )

    assert calls == [("t3", TaskStatus.APPROVED)]


def test_audit_fail_path_unchanged(monkeypatch):
    """Regression: a failed audit still emits REJECTED with reasons joined."""
    calls = []

    monkeypatch.setattr(
        orchestrator_module,
        "run_hard_audit",
        lambda _: SimpleNamespace(passed=False, reasons=["bad"]),
    )
    monkeypatch.setattr(
        orchestrator_module,
        "update_task_status",
        lambda *args: calls.append(args),
    )

    orchestrator_module._on_processor_done(
        SimpleNamespace(task_id="t4", note_path="note.md")
    )

    assert calls == [("t4", TaskStatus.REJECTED, "bad")]
