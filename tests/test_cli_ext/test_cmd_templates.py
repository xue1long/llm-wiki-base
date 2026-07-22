"""Tests for templates CLI."""
from src.cli_ext.templates_cmd import cmd_templates_list, cmd_templates_show
from src.templates.loader import load, list_bundled


def test_list_bundled_includes_research():
    """Bundled 'research' template exists."""
    names = list_bundled()
    assert "research" in names


def test_load_research_template():
    """Loaded template has expected files."""
    t = load("research")
    assert t.name == "research"
    assert "purpose.md" in t.files
    assert "schema.md" in t.files


def test_load_unknown_template_raises():
    import pytest
    with pytest.raises(FileNotFoundError):
        load("does_not_exist_xyz")


def test_cmd_templates_list_prints_research(capsys):
    args = type("Args", (), {})()
    cmd_templates_list(args)
    out = capsys.readouterr().out
    assert "research" in out


def test_cmd_templates_show_unknown_exits(capsys):
    import pytest
    args = type("Args", (), {"name": "nope_xyz"})()
    with pytest.raises(SystemExit) as exc:
        cmd_templates_show(args)
    assert exc.value.code == 2
