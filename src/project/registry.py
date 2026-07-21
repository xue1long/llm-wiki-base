"""Global project registry — UUID → metadata mapping persisted to registry.json."""
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


from . import paths
from .paths import registry_path as _default_registry_path


_logger = logging.getLogger(__name__)


def registry_path() -> Path:
    """Alias of paths.registry_path() — for downstream monkeypatching."""
    return _default_registry_path()


@dataclass
class ProjectRegistryEntry:
    """One project's metadata in the global registry."""
    id: str
    path: str                        # absolute filesystem path
    name: str                        # human-readable
    last_opened: int                 # unix ms
    schema_version: str = "v2.0"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectRegistryEntry":
        return cls(
            id=data["id"],
            path=data["path"],
            name=data["name"],
            last_opened=data["last_opened"],
            schema_version=data.get("schema_version", "v2.0"),
        )


@dataclass
class GlobalRegistry:
    """All known projects."""
    projects: dict[str, ProjectRegistryEntry] = field(default_factory=dict)  # id → entry


@dataclass
class LastProjectPointer:
    id: str
    path: str


class GlobalRegistryStore:
    """Static methods for registry CRUD. All I/O goes through `paths.registry_path()`."""

    @staticmethod
    def _path() -> Path:
        """Pluggable path (test override via monkeypatch)."""
        return paths.registry_path()

    @classmethod
    def load(cls) -> GlobalRegistry:
        """Load registry from disk. Returns empty on missing/corrupt."""
        path = cls._path()
        if not path.exists():
            return GlobalRegistry()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            projects = {
                pid: ProjectRegistryEntry.from_dict(pdata)
                for pid, pdata in data.get("projects", {}).items()
            }
            return GlobalRegistry(projects=projects)
        except (json.JSONDecodeError, KeyError, ValueError, TypeError, AttributeError) as e:
            _logger.warning(f"[registry] corrupt registry.json: {e}; using empty")
            # Backup corrupt file
            try:
                path.rename(path.with_suffix(".json.bak"))
            except OSError:
                pass
            return GlobalRegistry()

    @classmethod
    def save(cls, reg: GlobalRegistry) -> None:
        """Persist registry to disk via atomic write (write to .tmp + os.replace)."""
        path = cls._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        data = {
            "version": 1,
            "projects": {pid: e.to_dict() for pid, e in reg.projects.items()},
        }
        tmp_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(tmp_path, path)

    @classmethod
    def upsert(cls, entry: ProjectRegistryEntry) -> None:
        """Insert or update entry by ID."""
        reg = cls.load()
        reg.projects[entry.id] = entry
        cls.save(reg)

    @classmethod
    def remove(cls, project_id: str) -> None:
        """Remove entry by ID. No-op if not present."""
        reg = cls.load()
        if project_id in reg.projects:
            del reg.projects[project_id]
            cls.save(reg)

    @classmethod
    def load_last_project(cls) -> "LastProjectPointer | None":  # type: ignore
        from .paths import last_project_path as _last_path
        path = _last_path()
        if not path.exists():
            return None
        try:
            import json
            data = json.loads(path.read_text(encoding="utf-8"))
            return LastProjectPointer(id=data["id"], path=data["path"])
        except (json.JSONDecodeError, KeyError, OSError):
            return None

    @classmethod
    def save_last_project(cls, id: str, path: str) -> None:
        from .paths import last_project_path as _last_path
        p = _last_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        import json
        p.write_text(json.dumps({"id": id, "path": path}, indent=2), encoding="utf-8")

    @classmethod
    def by_id(cls, project_id: str) -> ProjectRegistryEntry | None:
        reg = cls.load()
        return reg.projects.get(project_id)

    @classmethod
    def by_name(cls, name: str) -> ProjectRegistryEntry | None:
        reg = cls.load()
        for entry in reg.projects.values():
            if entry.name == name:
                return entry
        return None

    @classmethod
    def by_path(cls, path: Path | str) -> ProjectRegistryEntry | None:
        """Find entry whose path matches (after canonicalization)."""
        reg = cls.load()
        canonical = Path(path).resolve().as_posix()
        for entry in reg.projects.values():
            if Path(entry.path).resolve().as_posix() == canonical:
                return entry
        return None
