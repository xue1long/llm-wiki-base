import json
from types import SimpleNamespace

from src.pipeline.quarantine import quarantine_task


def test_quarantine_redacts_secrets_and_keeps_summary(tmp_path):
    context = SimpleNamespace(project_root=tmp_path, task_id="task-1", run_id="run-1", source_hash="hash")
    path = quarantine_task(
        context,
        reason_code="provider_failure",
        errors=["Authorization: Bearer secret-token"],
        artifacts={"source_text": "private source", "detail": "x"},
    )
    payload = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    raw = json.dumps(payload)
    assert "secret-token" not in raw
    assert "private source" not in raw
    assert payload["reason_code"] == "provider_failure"
