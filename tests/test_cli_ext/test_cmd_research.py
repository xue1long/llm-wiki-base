"""Tests for the deep-research CLI subcommands (routing + cmd_research_list)."""
import argparse

from src.cli_ext.research_cmd import cmd_research_list


def test_research_cli_routes_run(capsys, monkeypatch):
    """`research run --help` should be parseable and route to cmd_research_run."""
    from unittest.mock import MagicMock
    from src.cli_ext import research_cmd

    async def fake_run_deep_research(ctx, **kwargs):
        return {"task_id": "t1", "synthesis_path": "wiki/synthesis/x.md",
                "sources": [{"title": "A", "url": "https://a", "snippet": "x"}],
                "ingest_task_ids": []}

    # Patch the name *as imported by* research_cmd (not src.research.runner).
    monkeypatch.setattr(research_cmd, "run_deep_research", fake_run_deep_research)
    monkeypatch.setattr(research_cmd.ProjectContext, "resolve", classmethod(lambda cls, *a, **k: MagicMock()))

    args = argparse.Namespace(
        project=None, topic="Test", from_review_id=None, ingest=False, top_k=10,
    )
    research_cmd.cmd_research_run(args)
    out = capsys.readouterr().out
    assert "Task: t1" in out
    assert "Synthesis: wiki/synthesis/x.md" in out
    assert "Sources: 1" in out


def test_research_cli_list_placeholder(capsys):
    """research list prints MVP placeholder message."""
    args = argparse.Namespace()
    cmd_research_list(args)
    out = capsys.readouterr().out
    assert "No persistence in MVP" in out


def test_research_cli_argparser_parses():
    """Argparse should accept `research run <topic>` shape and route correctly."""
    from src.cli_ext.research_cmd import add_research_subcommands
    import argparse
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    add_research_subcommands(sub)
    ns = parser.parse_args(["research", "run", "quantum computing"])
    assert ns.research_command == "run"
    assert ns.topic == "quantum computing"
    assert ns.ingest is False
    assert ns.top_k == 10
    ns2 = parser.parse_args(["research", "run", "x", "--ingest", "--top-k", "5"])
    assert ns2.ingest is True
    assert ns2.top_k == 5
    ns3 = parser.parse_args(["research", "list"])
    assert ns3.research_command == "list"
    ns4 = parser.parse_args(["research", "show", "research-foo-2026-07-22"])
    assert ns4.task_id == "research-foo-2026-07-22"
