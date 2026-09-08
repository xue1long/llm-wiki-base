from __future__ import annotations

import json

from src.cli_ext import lineage_cmd
from src.lineage import LineageStore


def test_lineage_show_includes_book_run_and_member_status(tmp_path, monkeypatch, capsys):
    store = LineageStore.open(tmp_path)
    store.register_source("src-1", "raw/a.md", "a" * 64, "ingested")
    run_id = store.create_build_run(("src-1",), "src-1:" + "a" * 64)
    store.record_build_member(run_id, "src-1", "chapter-1", "staged")

    monkeypatch.setattr(lineage_cmd, "_resolve", lambda _project: type("Ctx", (), {"path": tmp_path})())
    lineage_cmd.cmd_lineage_show(type("Args", (), {"project": "p1", "json": True})())

    payload = json.loads(capsys.readouterr().out)
    assert payload["build_runs"][0]["run_id"] == run_id
    assert payload["build_members"][0]["status"] == "staged"
