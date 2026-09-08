from __future__ import annotations

import argparse
import sys
import types
from pathlib import Path
from types import SimpleNamespace

from src.cli_ext import book_cmd


def _args(root: Path, **overrides):
    values = dict(project="p", output_dir="book-wiki", use_llm=False,
                  polish=False, apply=False, max_attempts=3,
                  max_input_tokens=None, max_output_tokens=None, json=True,
                  encyclopedic=False, quality_gate="rule", rubric=None)
    values.update(overrides)
    return argparse.Namespace(**values)


def test_dry_run_resolves_output_relative_to_project_and_calls_compiler(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(book_cmd, "_resolve", lambda _project: SimpleNamespace(path=tmp_path))
    monkeypatch.setattr(book_cmd, "run_preflight", lambda *a, **kw: SimpleNamespace(ok=True, errors=()))
    compiler = types.ModuleType("src.kc.views.book.wiki.compiler")
    seen = {}
    def build_from_wiki(*args, **kwargs):
        seen.update(kwargs)
        seen["root"] = args[0]
        return {"status": "dry-run"}
    compiler.build_from_wiki = build_from_wiki
    monkeypatch.setitem(sys.modules, compiler.__name__, compiler)

    assert book_cmd.cmd_book_build_from_wiki(_args(tmp_path)) == 0
    assert seen["root"] == tmp_path
    assert seen["output_dir"] == tmp_path / "book-wiki"
    assert seen["apply"] is False
    assert json_status(capsys.readouterr().out) == "dry-run"


def test_preflight_failure_uses_declared_exit_code(monkeypatch, tmp_path):
    monkeypatch.setattr(book_cmd, "_resolve", lambda _project: SimpleNamespace(path=tmp_path))
    error = SimpleNamespace(code="E_DISK_PRESSURE", message="low disk")
    monkeypatch.setattr(book_cmd, "run_preflight", lambda *a, **kw: SimpleNamespace(ok=False, errors=(error,)))
    try:
        book_cmd.cmd_book_build_from_wiki(_args(tmp_path, json=False))
    except SystemExit as exc:
        assert exc.code == 8
    else:
        raise AssertionError("preflight failure must exit")


def json_status(output: str) -> str:
    import json
    return json.loads(output)["status"]


def test_v4_flags_are_forwarded(monkeypatch, tmp_path):
    monkeypatch.setattr(book_cmd, "_resolve", lambda _project: SimpleNamespace(path=tmp_path))
    monkeypatch.setattr(book_cmd, "run_preflight", lambda *a, **kw: SimpleNamespace(ok=True, errors=()))
    seen = {}
    compiler = types.ModuleType("src.kc.views.book.wiki.compiler")
    compiler.build_from_wiki = lambda *a, **kw: seen.update(kw) or {"status": "dry-run"}
    monkeypatch.setitem(sys.modules, compiler.__name__, compiler)
    args = _args(tmp_path, use_llm=True, encyclopedic=True, quality_gate="both", rubric="r.yaml")
    assert book_cmd.cmd_book_build_from_wiki(args) == 0
    assert seen["encyclopedic"] is True
    assert seen["quality_gate"] == "both"
    assert seen["rubric"] == "r.yaml"


def test_encyclopedic_requires_llm_exit_6(monkeypatch, tmp_path):
    monkeypatch.setattr(book_cmd, "_resolve", lambda _project: SimpleNamespace(path=tmp_path))
    monkeypatch.setattr(book_cmd, "run_preflight", lambda *a, **kw: SimpleNamespace(ok=True, errors=()))
    try:
        book_cmd.cmd_book_build_from_wiki(_args(tmp_path, encyclopedic=True))
    except SystemExit as exc:
        assert exc.code == book_cmd.EXIT_BUDGET_EXHAUSTED
    else:
        raise AssertionError("encyclopedic mode must require --use-llm")
