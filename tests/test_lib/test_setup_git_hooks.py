import os
import subprocess
import sys
from pathlib import Path

from scripts import setup_git_hooks


def _repo(tmp_path: Path, *, matching_docs: bool = True) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    hooks = repo / ".git" / "hooks"
    scripts = repo / "scripts"
    hooks.mkdir(parents=True)
    scripts.mkdir()
    agents = "# AGENTS.md\n\nAgent instructions\n\nshared body\n"
    claude = (
        "# CLAUDE.md\n\nClaude instructions\n\nshared body\n"
        if matching_docs
        else "# CLAUDE.md\n\nClaude instructions\n\nother body\n"
    )
    (repo / "AGENTS.md").write_text(agents, encoding="utf-8")
    (repo / "CLAUDE.md").write_text(claude, encoding="utf-8")
    (scripts / "sync_wiki_spec.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    return repo, hooks


def test_install_uses_explicit_local_target_and_is_idempotent(tmp_path: Path) -> None:
    repo, hooks = _repo(tmp_path)

    first = setup_git_hooks.install(repo, hooks)
    content = first.read_bytes()
    second = setup_git_hooks.install(repo, hooks)

    assert first == hooks / "pre-commit"
    assert second.read_bytes() == content
    assert str(repo).replace("\\", "/").encode() in content
    assert b"AGENTS.md" in content and b"CLAUDE.md" in content
    assert b"sync_wiki_spec.py" in content
    if os.name != "nt":
        assert second.stat().st_mode & 0o111


def test_hook_blocks_unsynchronized_docs(tmp_path: Path) -> None:
    repo, hooks = _repo(tmp_path, matching_docs=False)
    hook = setup_git_hooks.install(repo, hooks)

    result = subprocess.run([sys.executable, str(hook)], cwd=repo, capture_output=True, text=True)

    assert result.returncode != 0
    assert "body content differs" in result.stdout


def test_install_does_not_follow_git_dir(tmp_path: Path, monkeypatch) -> None:
    repo, hooks = _repo(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setenv("GIT_DIR", str(elsewhere))

    hook = setup_git_hooks.install(repo, hooks)

    assert hook == hooks / "pre-commit"
    assert not (elsewhere / "hooks" / "pre-commit").exists()
