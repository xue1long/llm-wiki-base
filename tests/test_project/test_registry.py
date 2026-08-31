from pathlib import Path

from src.project.registry import (
    GlobalRegistryStore,
    ProjectRegistryEntry,
)


def test_load_returns_empty_when_no_file(tmp_path, monkeypatch):
    """load() returns empty GlobalRegistry when registry.json doesn't exist."""
    from src.project import paths

    monkeypatch.setattr(paths, "registry_path", lambda: tmp_path / "registry.json")

    reg = GlobalRegistryStore.load()
    assert reg.projects == {}


def test_load_returns_empty_when_registry_path_is_inaccessible(monkeypatch):
    from src.project import paths

    target = Path("C:/inaccessible/registry.json")
    monkeypatch.setattr(paths, "registry_path", lambda: target)
    original_exists = Path.exists

    def denied_exists(path):
        if path == target:
            raise PermissionError("denied")
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", denied_exists)

    assert GlobalRegistryStore.load().projects == {}


def test_upsert_and_load_roundtrip(tmp_path, monkeypatch):
    """upsert() persists to registry.json; load() reads it back."""
    from src.project import paths

    monkeypatch.setattr(paths, "registry_path", lambda: tmp_path / "registry.json")

    entry = ProjectRegistryEntry(
        id="uuid-1",
        path="/home/user/research",
        name="research",
        last_opened=1000,
        schema_version="v2.0",
    )
    GlobalRegistryStore.upsert(entry)

    reg = GlobalRegistryStore.load()
    assert "uuid-1" in reg.projects
    assert reg.projects["uuid-1"].name == "research"


def test_by_id_finds_existing(tmp_path, monkeypatch):
    """by_id() returns entry or None."""
    from src.project import paths

    monkeypatch.setattr(paths, "registry_path", lambda: tmp_path / "registry.json")

    entry = ProjectRegistryEntry(
        id="uuid-2",
        path="/p",
        name="novel",
        last_opened=2000,
        schema_version="v2.0",
    )
    GlobalRegistryStore.upsert(entry)

    found = GlobalRegistryStore.by_id("uuid-2")
    assert found is not None
    assert found.name == "novel"

    assert GlobalRegistryStore.by_id("nonexistent") is None


def test_by_name_finds_existing(tmp_path, monkeypatch):
    """by_name() returns entry or None."""
    from src.project import paths

    monkeypatch.setattr(paths, "registry_path", lambda: tmp_path / "registry.json")

    entry = ProjectRegistryEntry(
        id="uuid-3",
        path="/p3",
        name="research",
        last_opened=3000,
        schema_version="v2.0",
    )
    GlobalRegistryStore.upsert(entry)

    found = GlobalRegistryStore.by_name("research")
    assert found is not None
    assert found.id == "uuid-3"


def test_remove(tmp_path, monkeypatch):
    """remove() deletes entry from registry."""
    from src.project import paths

    monkeypatch.setattr(paths, "registry_path", lambda: tmp_path / "registry.json")

    entry = ProjectRegistryEntry(
        id="uuid-4", path="/p4", name="x", last_opened=4000, schema_version="v2.0"
    )
    GlobalRegistryStore.upsert(entry)
    GlobalRegistryStore.remove("uuid-4")
    assert GlobalRegistryStore.by_id("uuid-4") is None


def test_corrupt_registry_returns_empty(tmp_path, monkeypatch):
    """Corrupt registry.json → load() returns empty registry + .bak backup."""
    from src.project import paths

    registry_file = tmp_path / "registry.json"
    registry_file.write_text("not json {{{", encoding="utf-8")
    monkeypatch.setattr(paths, "registry_path", lambda: registry_file)

    reg = GlobalRegistryStore.load()
    assert reg.projects == {}
    # Backup created
    assert (tmp_path / "registry.json.bak").exists()
