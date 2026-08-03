"""Test that src/cli_ext/templates_cmd.py uses WikiPaths(ctx.path) correctly."""
from argparse import Namespace



def test_cmd_templates_apply_uses_paths(tmp_path, monkeypatch):
    """Verify cmd_templates_apply uses WikiPaths(ctx.path) for template application."""
    from src.cli_ext import templates_cmd
    from src.templates.loader import Template
    from src.project.context import ProjectContext

    # Mock ProjectContext.resolve to return ctx with .path only
    class FakeCtx:
        def __init__(self, path):
            self.path = path

    def fake_resolve(project_arg, by_id_only=False):
        return FakeCtx(tmp_path)

    monkeypatch.setattr(ProjectContext, "resolve", fake_resolve)

    # Mock template loader
    fake_template = Template(name="test-template", files={"test.md": "content"})

    def fake_load(name):
        return fake_template

    monkeypatch.setattr(templates_cmd, "load", fake_load)

    args = Namespace(project="test", name="test-template")

    # Should NOT raise AttributeError
    templates_cmd.cmd_templates_apply(args)

    # Verify file was written
    assert (tmp_path / "test.md").exists()


def test_cmd_templates_apply_does_not_access_ctx_paths(tmp_path, monkeypatch):
    """Regression: ctx.paths must NOT be accessed."""
    from src.cli_ext import templates_cmd
    from src.templates.loader import Template
    from src.project.context import ProjectContext

    class ExplodingCtx:
        def __init__(self, path):
            self.path = path

        @property
        def paths(self):
            raise AssertionError("ctx.paths must not be accessed")

    def fake_resolve(project_arg, by_id_only=False):
        return ExplodingCtx(tmp_path)

    monkeypatch.setattr(ProjectContext, "resolve", fake_resolve)

    fake_template = Template(name="test-template", files={"test.md": "content"})

    def fake_load(name):
        return fake_template

    monkeypatch.setattr(templates_cmd, "load", fake_load)

    args = Namespace(project="test", name="test-template")

    # Should not raise AssertionError
    templates_cmd.cmd_templates_apply(args)
