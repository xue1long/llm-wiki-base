"""Tests for the health CLI subcommand."""
import json

from src.cli_ext.health_cmd import cmd_health


def test_cmd_health_text_output(tmp_path, capsys):
    (tmp_path / "wiki" / "sources").mkdir(parents=True)
    (tmp_path / "wiki" / "sources" / "a.md").write_text(
        "---\nid: card_018f3a8e2b1c4_a3f9d12c_a\n---\nbody", encoding="utf-8",
    )
    (tmp_path / "raw" / "sources").mkdir(parents=True)
    (tmp_path / "raw" / "sources" / "a.pdf").write_bytes(b"x")

    args = type("Args", (), {
        "only": None, "skip": None, "strict": False, "json": False,
        "project": str(tmp_path),
    })()
    cmd_health(args)

    out = capsys.readouterr().out
    assert "H1" in out
    assert "[OK]" in out or "PASS" in out


def test_cmd_health_json_output(tmp_path, capsys):
    (tmp_path / "wiki" / "sources").mkdir(parents=True)
    (tmp_path / "wiki" / "sources" / "a.md").write_text(
        "---\nid: card_018f3a8e2b1c4_a3f9d12c_a\n---\nbody", encoding="utf-8",
    )

    args = type("Args", (), {
        "only": None, "skip": None, "strict": False, "json": True,
        "project": str(tmp_path),
    })()
    cmd_health(args)

    out = capsys.readouterr().out
    data = json.loads(out)
    assert "check_results" in data
    assert "H1" in data["check_results"]


def test_cmd_health_strict_exits_1_on_error(tmp_path):
    (tmp_path / "wiki" / "sources").mkdir(parents=True)
    (tmp_path / "wiki" / "sources" / "a.md").write_text(
        "---\nid: card_018f3a8e2b1c4_a3f9d12c_a\nsources: [raw/sources/missing.pdf]\n---\nbody",
        encoding="utf-8",
    )

    import pytest
    args = type("Args", (), {
        "only": None, "skip": None, "strict": True, "json": False,
        "project": str(tmp_path),
    })()
    with pytest.raises(SystemExit) as exc:
        cmd_health(args)
    assert exc.value.code == 1


def test_cmd_health_only_flag(tmp_path, capsys):
    (tmp_path / "wiki" / "sources").mkdir(parents=True)
    (tmp_path / "wiki" / "sources" / "a.md").write_text(
        "---\nid: card_018f3a8e2b1c4_a3f9d12c_a\n---\nbody [[ghost]]",
        encoding="utf-8",
    )

    args = type("Args", (), {
        "only": ["H1"], "skip": None, "strict": False, "json": False,
        "project": str(tmp_path),
    })()
    cmd_health(args)

    out = capsys.readouterr().out
    assert "H1" in out
    assert "H2" not in out
    assert "H4" not in out
