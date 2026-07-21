# tests/test_project/test_identity.py
import json
from pathlib import Path

from src.project.identity import ProjectIdentity, ensure_project_id


def test_ensure_project_id_creates_when_missing(tmp_path: Path):
    """First call to ensure_project_id generates UUID + writes project.json."""
    project_path = tmp_path / "wiki_root"
    project_path.mkdir()

    uuid = ensure_project_id(project_path)

    # UUID v4 format (8-4-4-4-12)
    assert len(uuid) == 36
    assert uuid.count("-") == 4

    # project.json created
    project_json = project_path / ".llm-wiki" / "project.json"
    assert project_json.exists()

    data = json.loads(project_json.read_text(encoding="utf-8"))
    assert data["id"] == uuid
    assert "created_at" in data
    assert isinstance(data["created_at"], int)


def test_ensure_project_id_returns_existing(tmp_path: Path):
    """Second call returns same UUID without modifying file."""
    project_path = tmp_path / "wiki_root"
    project_path.mkdir()

    first = ensure_project_id(project_path)
    second = ensure_project_id(project_path)

    assert first == second


def test_ensure_project_id_recovers_from_corrupt_json(tmp_path: Path):
    """Corrupt project.json triggers regeneration of UUID."""
    project_path = tmp_path / "wiki_root"
    project_path.mkdir()
    project_json = project_path / ".llm-wiki" / "project.json"
    project_json.parent.mkdir(parents=True, exist_ok=True)
    project_json.write_text("not valid json {{{", encoding="utf-8")

    uuid = ensure_project_id(project_path)

    assert len(uuid) == 36
    # File is now valid JSON
    data = json.loads(project_json.read_text(encoding="utf-8"))
    assert data["id"] == uuid


def test_project_identity_dataclass_roundtrip():
    """ProjectIdentity.to_dict() / from_dict() round-trip preserves fields."""
    ident = ProjectIdentity(
        id="abc-123",
        name="research",
        created_at=1000,
        schema_version="v2.0",
    )
    d = ident.to_dict()
    assert d["id"] == "abc-123"
    restored = ProjectIdentity.from_dict(d)
    assert restored.id == ident.id
    assert restored.name == ident.name