# tests/test_project/test_discovery.py
from pathlib import Path

from src.project.discovery import (
    is_kb_root,
    discover_existing_kbs,
    auto_register_on_first_run,
)


def test_is_kb_root_v2(tmp_path: Path):
    """Directory with .index/schema_version is v2.0 KB."""
    kb = tmp_path / "kb_v2"
    kb.mkdir()
    (kb / ".index").mkdir()
    (kb / ".index" / "schema_version").write_text("v2.0", encoding="utf-8")
    assert is_kb_root(kb) is True


def test_is_kb_root_v1(tmp_path: Path):
    """Directory with Notes/ subdir is v1.0 KB."""
    kb = tmp_path / "kb_v1"
    kb.mkdir()
    (kb / "Notes").mkdir()
    assert is_kb_root(kb) is True


def test_is_kb_root_not_a_kb(tmp_path: Path):
    """Plain directory without markers is NOT a KB."""
    plain = tmp_path / "plain"
    plain.mkdir()
    assert is_kb_root(plain) is False


def test_discover_existing_kbs_finds_in_default_paths(tmp_path, monkeypatch):
    """discover_existing_kbs scans DEFAULT_SEARCH_PATHS for KBs."""
    from src.project import paths
    monkeypatch.setattr(paths, "config_dir", lambda: tmp_path / "config")

    # Create fake ~/Documents and ~/Notes
    docs = tmp_path / "Documents"
    notes = tmp_path / "Notes"
    docs.mkdir()
    notes.mkdir()
    # KB inside Documents
    (docs / "research").mkdir()
    (docs / "research" / ".index").mkdir()
    (docs / "research" / ".index" / "schema_version").write_text("v2.0")
    # KB inside Notes (one level deeper)
    (notes / "novel").mkdir()
    (notes / "novel" / "Notes").mkdir()
    # Not a KB
    (docs / "notakb").mkdir()

    monkeypatch.setattr(
        "src.project.discovery.DEFAULT_SEARCH_PATHS",
        [docs, notes],
        raising=False,
    )

    found = discover_existing_kbs()
    paths_found = sorted(str(p) for p in found)
    assert any("research" in p for p in paths_found)
    assert any("novel" in p for p in paths_found)
    assert not any("notakb" in p for p in paths_found)


def test_auto_register_on_first_run(tmp_path, monkeypatch):
    """First run with no registry → auto-discovers and registers KBs."""
    from src.project import paths, registry

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    docs = tmp_path / "Documents"
    docs.mkdir()
    (docs / "research").mkdir()
    (docs / "research" / ".index").mkdir()
    (docs / "research" / ".index" / "schema_version").write_text("v2.0")

    monkeypatch.setattr(paths, "config_dir", lambda: config_dir)
    monkeypatch.setattr(registry, "_default_registry_path", lambda: config_dir / "registry.json")
    monkeypatch.setattr("src.project.discovery.DEFAULT_SEARCH_PATHS", [docs], raising=False)

    # No registry.json yet
    assert not (config_dir / "registry.json").exists()

    contexts = auto_register_on_first_run()

    # Now registry.json exists with one entry
    assert (config_dir / "registry.json").exists()
    assert len(contexts) == 1
    assert "research" in str(contexts[0].path)


def test_auto_register_no_op_when_registry_exists(tmp_path, monkeypatch):
    """If registry.json already exists, auto_register is a no-op."""
    from src.project import paths, registry

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    docs = tmp_path / "Documents"
    docs.mkdir()
    (docs / "research").mkdir()
    (docs / "research" / ".index").mkdir()

    # Pre-existing registry
    monkeypatch.setattr(paths, "config_dir", lambda: config_dir)
    monkeypatch.setattr(registry, "_default_registry_path", lambda: config_dir / "registry.json")
    pre_registry = config_dir / "registry.json"
    pre_registry.write_text('{"version": 1, "projects": {}}', encoding="utf-8")
    original_content = pre_registry.read_text(encoding="utf-8")

    monkeypatch.setattr("src.project.discovery.DEFAULT_SEARCH_PATHS", [docs], raising=False)

    contexts = auto_register_on_first_run()

    # Registry file untouched
    assert pre_registry.read_text(encoding="utf-8") == original_content
    assert contexts == []


def test_auto_register_tolerates_unreadable_registry(tmp_path, monkeypatch):
    """A registry permission error must not abort server startup."""
    from src.project import registry

    monkeypatch.setattr("src.project.discovery.discover_existing_kbs", lambda: [])
    monkeypatch.setattr(
        registry,
        "registry_path",
        lambda: (_ for _ in ()).throw(PermissionError("denied")),
    )

    assert auto_register_on_first_run() == []
