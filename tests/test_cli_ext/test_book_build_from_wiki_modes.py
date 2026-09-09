from __future__ import annotations

import argparse
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.cli import build_parser
from src.cli_ext import book_cmd


def _parse(*extra: str) -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args(
        ["book", "build-from-wiki", "--project", "p", *extra]
    )
    validate = getattr(args, "validate", None)
    if callable(validate):
        validate(args, parser)
    return args


def test_default_mode_is_plan() -> None:
    args = _parse()

    assert args.build_mode == "plan"
    assert args.use_llm is False
    assert args.polish is False
    assert args.max_attempts == 1


@pytest.mark.parametrize(
    ("flag", "expected_mode"),
    [("--preview", "preview"), ("--apply", "apply")],
)
def test_formal_llm_modes_are_explicit(flag: str, expected_mode: str) -> None:
    args = _parse(flag)

    assert args.build_mode == expected_mode


def test_formal_modes_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit):
        _parse("--plan", "--preview")


def test_apply_from_requires_apply() -> None:
    with pytest.raises(SystemExit):
        _parse("--apply-from", "a" * 32)


def test_apply_from_skips_preflight_and_forwards_promotion_id(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        book_cmd, "_resolve", lambda _project: SimpleNamespace(path=tmp_path)
    )
    monkeypatch.setattr(
        book_cmd,
        "run_preflight",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("preflight must be skipped")),
    )
    compiler = types.ModuleType("src.kc.views.book.wiki.compiler")
    seen: dict[str, object] = {}

    def build_from_wiki(*args, **kwargs):
        seen.update(kwargs)
        return {"status": "committed"}

    compiler.build_from_wiki = build_from_wiki
    monkeypatch.setitem(sys.modules, compiler.__name__, compiler)

    args = _parse("--apply", "--apply-from", "a" * 32)
    assert book_cmd.cmd_book_build_from_wiki(args) == 0
    assert seen["apply"] is True
    assert seen["apply_from"] == "a" * 32
    assert seen["use_llm"] is False
    assert seen["polish"] is False


def test_book_result_reports_vectors_are_separate(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.setattr(
        book_cmd, "_resolve", lambda _project: SimpleNamespace(path=tmp_path)
    )
    monkeypatch.setattr(
        book_cmd,
        "run_preflight",
        lambda *args, **kwargs: SimpleNamespace(ok=True, errors=()),
    )
    compiler = types.ModuleType("src.kc.views.book.wiki.compiler")
    compiler.build_from_wiki = lambda *args, **kwargs: {"status": "planned"}
    monkeypatch.setitem(sys.modules, compiler.__name__, compiler)

    args = _parse("--plan", "--json")
    assert book_cmd.cmd_book_build_from_wiki(args) == 0
    output = capsys.readouterr().out
    assert '"vector_index": "not_updated"' in output
    assert "vector status" in output


@pytest.mark.parametrize("legacy_flag", ["--use-llm", "--polish"])
def test_plan_rejects_legacy_llm_flags(legacy_flag: str) -> None:
    with pytest.raises(SystemExit):
        _parse(legacy_flag)


def test_legacy_llm_pair_remains_parseable_for_compatibility() -> None:
    args = _parse("--use-llm", "--polish")

    assert args.build_mode == "preview"
    assert args.use_llm is True
    assert args.polish is True


@pytest.mark.parametrize("flag", ["--preview", "--apply"])
def test_command_maps_formal_llm_modes_to_body_polishing(
    monkeypatch, tmp_path: Path, flag: str
) -> None:
    monkeypatch.setattr(
        book_cmd, "_resolve", lambda _project: SimpleNamespace(path=tmp_path)
    )
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        book_cmd,
        "run_preflight",
        lambda *args, **kwargs: SimpleNamespace(ok=True, errors=()),
    )
    compiler = types.ModuleType("src.kc.views.book.wiki.compiler")

    def build_from_wiki(*args, **kwargs):
        seen.update(kwargs)
        return {"status": "committed" if kwargs["apply"] else "preview"}

    compiler.build_from_wiki = build_from_wiki
    monkeypatch.setitem(sys.modules, compiler.__name__, compiler)

    args = _parse(flag)
    assert book_cmd.cmd_book_build_from_wiki(args) == 0

    assert seen["use_llm"] is True
    assert seen["polish"] is True
    assert seen["apply"] is (flag == "--apply")


def test_legacy_namespace_cannot_create_outline_only_mode(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        book_cmd, "_resolve", lambda _project: SimpleNamespace(path=tmp_path)
    )
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        book_cmd,
        "run_preflight",
        lambda *args, **kwargs: SimpleNamespace(ok=True, errors=()),
    )
    compiler = types.ModuleType("src.kc.views.book.wiki.compiler")

    def build_from_wiki(*args, **kwargs):
        seen.update(kwargs)
        return {"status": "preview"}

    compiler.build_from_wiki = build_from_wiki
    monkeypatch.setitem(sys.modules, compiler.__name__, compiler)

    args = _parse()
    delattr(args, "build_mode")
    args.use_llm = True
    args.polish = False

    assert book_cmd.cmd_book_build_from_wiki(args) == 0
    assert seen["use_llm"] is True
    assert seen["polish"] is True
    assert seen["apply"] is False
