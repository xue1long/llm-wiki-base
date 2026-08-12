import pytest

from src.cli_ext import project_resolve as cli_project
from src.project.context import ProjectNotFoundError


def test_resolve_cli_project_preserves_return_shapes_and_mode(monkeypatch):
    calls = []
    ctx, paths = object(), object()

    def resolve_with_paths(arg, by_id_only=True):
        calls.append(("paths", arg, by_id_only))
        return ctx, paths

    def resolve_context(arg, by_id_only=True):
        calls.append(("ctx", arg, by_id_only))
        return ctx

    monkeypatch.setattr(cli_project, "resolve_project", resolve_with_paths)
    monkeypatch.setattr(cli_project, "resolve_ctx_only", resolve_context)

    assert cli_project.resolve_cli_project("path", by_id_only=False) == (ctx, paths)
    assert cli_project.resolve_cli_project("id", with_paths=False) is ctx
    assert calls == [("paths", "path", False), ("ctx", "id", True)]


def test_resolve_cli_project_keeps_exit_two_error_contract(monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise ProjectNotFoundError("missing project")

    monkeypatch.setattr(cli_project, "resolve_project", fail)

    with pytest.raises(SystemExit) as exc_info:
        cli_project.resolve_cli_project("missing")

    assert exc_info.value.code == 2
    assert capsys.readouterr().err == "Error: missing project\n"
