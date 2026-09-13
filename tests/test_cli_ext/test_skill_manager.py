from __future__ import annotations

import json


def test_cli_registers_skill_manager_json_commands():
    from src.cli import build_parser

    args = build_parser().parse_args(["skill-manager", "list", "--json"])

    assert args.command == "skill-manager"
    assert args.skill_manager_command == "list"
    assert args.json is True


def test_cli_list_emits_json(monkeypatch, capsys):
    from src.cli_ext import skill_manager_cmd

    monkeypatch.setattr(skill_manager_cmd.service, "list_library", lambda: {"artifacts": []})
    skill_manager_cmd.cmd_skill_manager_list(type("Args", (), {"json": True})())

    assert json.loads(capsys.readouterr().out) == {"artifacts": []}
