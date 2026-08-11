"""Audit I6/M1 regression: templates_cmd.apply writes through safe_write.

Previously ``dest.write_text(content, encoding="utf-8")`` produced torn files
on a crash mid-write and was not AtomicContext-aware. After the fix the
call goes through ``src.lib.write_hooks.safe_write``.
"""
from argparse import Namespace
from pathlib import Path

from src.cli_ext import templates_cmd
from src.lib import write_hooks
from src.templates.loader import Template


def test_cmd_templates_apply_uses_safe_write(tmp_path, monkeypatch):
    """cmd_templates_apply must route through safe_write, not raw write_text."""
    from src.project.context import ProjectContext

    class FakeCtx:
        def __init__(self, path):
            self.path = path

    monkeypatch.setattr(ProjectContext, "resolve", lambda arg, by_id_only=False: FakeCtx(tmp_path))

    fake_template = Template(name="t", files={"x.md": "hello"})
    monkeypatch.setattr(templates_cmd, "load", lambda name: fake_template)

    # Capture calls to safe_write (don't stub it — the real one is the
    # implementation we want exercised; we just want a call record).
    calls = []
    real_safe_write = write_hooks.safe_write

    def spy_safe_write(path, content):
        calls.append((Path(path), content))
        return real_safe_write(path, content)

    monkeypatch.setattr(templates_cmd, "safe_write", spy_safe_write)

    args = Namespace(project="p", name="t")
    templates_cmd.cmd_templates_apply(args)

    assert calls, "safe_write must have been called at least once"
    assert (Path(tmp_path) / "x.md") in [Path(p) for (p, _) in calls]
    assert any(c == "hello" for (_p, c) in calls)
