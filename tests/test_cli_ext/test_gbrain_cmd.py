from __future__ import annotations

import argparse
import json

from src.cli import build_parser
from src.cli_ext.gbrain_cmd import cmd_gbrain_runtime_status


def test_gbrain_runtime_status_parser_wires_handler() -> None:
    args = build_parser().parse_args(["gbrain", "runtime-status", "--json"])

    assert args.func is cmd_gbrain_runtime_status
    assert args.json is True


def test_gbrain_runtime_status_persists_missing_report(tmp_path, capsys) -> None:
    cmd_gbrain_runtime_status(
        argparse.Namespace(
            project_root=str(tmp_path), version=None, timeout=0.1, json=True
        )
    )

    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "missing"
    assert json.loads(
        (tmp_path / ".index" / "gbrain" / "runtime-state.json").read_text(
            encoding="utf-8"
        )
    ) == report
