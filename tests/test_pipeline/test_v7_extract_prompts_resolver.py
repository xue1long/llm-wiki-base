"""T1.4: resolver three-layer override + D9 whitelist + D6 hot-reload."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from src.pipeline.v7_extract.prompts import resolver as r
from src.pipeline.v7_extract.prompts.parser import PromptParseError
from src.pipeline.v7_extract.prompts.resolver import (
    BUNDLED_ROOT,
    PromptNotFoundError,
    PromptPathNotAllowedError,
    resolve,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _scrub_temp_env(monkeypatch):
    """Disable the D9 TEMP/TMPDIR checks for the duration of a test.

    pytest's tmp_path lives under the OS temp dir, so without scrubbing
    the env vars the D9 whitelist rejects every project_root we use.
    """
    for var in ("TMPDIR", "TEMP", "TMP"):
        monkeypatch.delenv(var, raising=False)


_VALID_TOML = """
[meta]
prompt_kind = "classify"
version = "1.0"

[system]
text = "SYS"

[user]
template = "Classify {content}"
"""


# ---------------------------------------------------------------------------
# Three-layer override priority
# ---------------------------------------------------------------------------

def test_resolve_uses_bundled_when_no_overrides(tmp_path, monkeypatch):
    """No project / user overrides → bundled wins."""
    _scrub_temp_env(monkeypatch)
    monkeypatch.setattr(r, "_user_root", lambda: tmp_path / "user_does_not_exist")
    monkeypatch.setattr(r, "BUNDLED_ROOT", tmp_path / "bundled")
    _write(tmp_path / "bundled" / "classify.toml", _VALID_TOML)
    tpl = resolve("classify", project_root=tmp_path / "project_does_not_exist")
    assert tpl.source == "bundled"
    assert tpl.path == tmp_path / "bundled" / "classify.toml"


def test_resolve_user_overrides_bundled(tmp_path, monkeypatch):
    _scrub_temp_env(monkeypatch)
    monkeypatch.setattr(r, "_user_root", lambda: tmp_path / "user")
    monkeypatch.setattr(r, "BUNDLED_ROOT", tmp_path / "bundled")
    _write(tmp_path / "bundled" / "classify.toml", _VALID_TOML)
    _write(tmp_path / "user" / "classify.toml", _VALID_TOML.replace('"SYS"', '"USER_SYS"'))
    tpl = resolve("classify", project_root=tmp_path / "no_project")
    assert tpl.source == "user"
    assert tpl.system_section == "USER_SYS"


def test_resolve_project_overrides_user(tmp_path, monkeypatch):
    _scrub_temp_env(monkeypatch)
    monkeypatch.setattr(r, "_user_root", lambda: tmp_path / "user")
    monkeypatch.setattr(r, "BUNDLED_ROOT", tmp_path / "bundled")
    project = tmp_path / "proj"
    _write(project / ".v7-prompts" / "classify.toml",
           _VALID_TOML.replace('"SYS"', '"PROJ_SYS"'))
    _write(tmp_path / "user" / "classify.toml",
           _VALID_TOML.replace('"SYS"', '"USER_SYS"'))
    _write(tmp_path / "bundled" / "classify.toml",
           _VALID_TOML.replace('"SYS"', '"BUNDLED_SYS"'))
    tpl = resolve("classify", project_root=project)
    assert tpl.source == "project"
    assert tpl.system_section == "PROJ_SYS"


def test_resolve_missing_kind_raises_not_found(tmp_path, monkeypatch):
    _scrub_temp_env(monkeypatch)
    monkeypatch.setattr(r, "_user_root", lambda: tmp_path / "user")
    monkeypatch.setattr(r, "BUNDLED_ROOT", tmp_path / "bundled")
    (tmp_path / "user").mkdir()
    (tmp_path / "bundled").mkdir()
    with pytest.raises(PromptNotFoundError, match="No prompt TOML found"):
        resolve("never_defined", project_root=tmp_path / "proj")


# ---------------------------------------------------------------------------
# D9: path whitelist
# ---------------------------------------------------------------------------

def test_resolve_rejects_TEMP_root(monkeypatch, tmp_path):
    """A17: paths under $TEMP (Windows temp dir) are rejected."""
    monkeypatch.setenv("TEMP", str(tmp_path))
    monkeypatch.setattr(r, "_user_root", lambda: tmp_path / "user_does_not_exist")
    monkeypatch.setattr(r, "BUNDLED_ROOT", tmp_path / "bundled")
    evil = tmp_path / "evil"
    with pytest.raises(PromptPathNotAllowedError, match="D9"):
        resolve("classify", project_root=evil)


def test_resolve_rejects_TMPDIR_root(monkeypatch, tmp_path):
    """D9: paths under $TMPDIR are rejected."""
    _scrub_temp_env(monkeypatch)
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setattr(r, "_user_root", lambda: tmp_path / "user_does_not_exist")
    monkeypatch.setattr(r, "BUNDLED_ROOT", tmp_path / "bundled")
    evil = tmp_path / "evil"
    with pytest.raises(PromptPathNotAllowedError, match="D9"):
        resolve("classify", project_root=evil)


def test_resolve_accepts_real_workspace_root(tmp_path, monkeypatch):
    """Real workspace path (not under any temp env) is accepted."""
    _scrub_temp_env(monkeypatch)
    monkeypatch.setattr(r, "_user_root", lambda: tmp_path / "user")
    monkeypatch.setattr(r, "BUNDLED_ROOT", tmp_path / "bundled")
    project = tmp_path / "proj"
    _write(project / ".v7-prompts" / "classify.toml", _VALID_TOML)
    _write(tmp_path / "bundled" / "classify.toml", _VALID_TOML)
    tpl = resolve("classify", project_root=project)
    assert tpl.source == "project"


# ---------------------------------------------------------------------------
# D6: hot reload
# ---------------------------------------------------------------------------

def test_resolve_hot_reload_picks_up_edits(tmp_path, monkeypatch):
    """A16: editing the TOML after first resolve takes effect immediately."""
    _scrub_temp_env(monkeypatch)
    monkeypatch.setattr(r, "_user_root", lambda: tmp_path / "user_does_not_exist")
    monkeypatch.setattr(r, "BUNDLED_ROOT", tmp_path / "bundled")
    bundled = tmp_path / "bundled" / "classify.toml"
    _write(bundled, _VALID_TOML)
    tpl1 = resolve("classify")
    assert tpl1.system_section == "SYS"

    # Author edits the file
    _write(bundled, _VALID_TOML.replace('"SYS"', '"SYS_V2"'))
    tpl2 = resolve("classify")
    assert tpl2.system_section == "SYS_V2", "hot reload must pick up edits"


# ---------------------------------------------------------------------------
# Error propagation
# ---------------------------------------------------------------------------

def test_resolve_propagates_parse_error(tmp_path, monkeypatch):
    _scrub_temp_env(monkeypatch)
    monkeypatch.setattr(r, "_user_root", lambda: tmp_path / "user_does_not_exist")
    monkeypatch.setattr(r, "BUNDLED_ROOT", tmp_path / "bundled")
    bundled = tmp_path / "bundled" / "classify.toml"
    bundled.parent.mkdir(parents=True)
    bundled.write_text("not = valid = toml ===", encoding="utf-8")
    with pytest.raises(PromptParseError, match="Invalid TOML"):
        resolve("classify")
