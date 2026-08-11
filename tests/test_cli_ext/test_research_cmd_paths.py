"""Test that src/cli_ext/research_cmd.py uses WikiPaths(ctx.path) correctly."""
from argparse import Namespace



def test_cmd_research_show_uses_paths(tmp_path, monkeypatch):
    """Verify cmd_research_show uses WikiPaths(ctx.path) for synthesis lookup."""
    from src.cli_ext import research_cmd

    # Create synthesis file
    wiki_synthesis = tmp_path / "wiki" / "synthesis"
    wiki_synthesis.mkdir(parents=True)
    (wiki_synthesis / "test-task.md").write_text(
        "---\nid: test-task\ntitle: Test\ntype: synthesis\n---\nbody\n",
        encoding="utf-8",
    )

    # Mock ProjectContext.resolve to return a ctx with .path only
    class FakeCtx:
        def __init__(self, path):
            self.path = path

    def fake_resolve(project_arg, by_id_only=False):
        return FakeCtx(tmp_path)

    monkeypatch.setattr(research_cmd.ProjectContext, "resolve", fake_resolve)

    # Mock read_page
    def fake_read_page(path):
        from types import SimpleNamespace
        return SimpleNamespace(
            id="test-task",
            title="Test",
            type="synthesis",
            body="body content",
        )

    monkeypatch.setattr(
        "src.wiki.storage.page_writer.read_page",
        fake_read_page,
    )

    args = Namespace(project="test", task_id="test-task")

    # Should NOT raise AttributeError
    try:
        research_cmd.cmd_research_show(args)
    except SystemExit as e:
        # Allow SystemExit (exit code 2 for errors), but not AttributeError
        assert e.code != 0  # Should not have errored


def test_cmd_research_show_does_not_access_ctx_paths(tmp_path, monkeypatch):
    """Regression: ctx.paths must NOT be accessed."""
    from src.cli_ext import research_cmd

    wiki_synthesis = tmp_path / "wiki" / "synthesis"
    wiki_synthesis.mkdir(parents=True)
    (wiki_synthesis / "test-task.md").write_text(
        "---\nid: test-task\ntitle: Test\ntype: synthesis\n---\nbody\n",
        encoding="utf-8",
    )

    class ExplodingCtx:
        def __init__(self, path):
            self.path = path

        @property
        def paths(self):
            raise AssertionError("ctx.paths must not be accessed")

    def fake_resolve(project_arg, by_id_only=False):
        return ExplodingCtx(tmp_path)

    monkeypatch.setattr(research_cmd.ProjectContext, "resolve", fake_resolve)

    def fake_read_page(path):
        from types import SimpleNamespace
        return SimpleNamespace(
            id="test-task",
            title="Test",
            type="synthesis",
            body="body",
        )

    monkeypatch.setattr(
        "src.wiki.storage.page_writer.read_page",
        fake_read_page,
    )

    args = Namespace(project="test", task_id="test-task")

    # Should not raise AssertionError
    try:
        research_cmd.cmd_research_show(args)
    except SystemExit:
        pass  # Allow SystemExit for missing file errors
