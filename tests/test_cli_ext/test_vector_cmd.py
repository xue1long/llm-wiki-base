from argparse import Namespace

from src.cli_ext import vector_cmd


def test_vector_reconcile_reports_publication_counters(monkeypatch, capsys):
    monkeypatch.setattr(vector_cmd, "resolve_project", lambda *args, **kwargs: (None, object()))
    monkeypatch.setattr(
        vector_cmd,
        "reconcile_pending",
        lambda *args, **kwargs: {
            "attempted": 2,
            "ok": 1,
            "failed": 0,
            "failed_ids": [],
            "intent": 1,
            "pending": 1,
            "recovered": 1,
            "orphaned": 0,
        },
    )

    vector_cmd.cmd_vector_reconcile(Namespace(project="demo"))

    output = capsys.readouterr().out
    assert "intent=1" in output
    assert "pending=1" in output
