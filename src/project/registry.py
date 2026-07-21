"""Global project registry — UUID → metadata mapping persisted to registry.json."""
import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


from . import paths


_logger = logging.getLogger(__name__)


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
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            _logger.warning(f"[registry] corrupt registry.json: {e}; using empty")
            # Backup corrupt file
            try:
                path.rename(path.with_suffix(".json.bak"))
            except OSError:
                pass
            return GlobalRegistry()

    @classmethod
    def save(cls, reg: GlobalRegistry) -> None:
        """Persist registry to disk. Creates parent dirs."""
        path = cls._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 1,
            "projects": {pid: e.to_dict() for pid, e in reg.projects.items()},
        }
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

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
    def by_path(cls, path: Path) -> ProjectRegistryEntry | None:
        """Find entry whose path matches (after canonicalization)."""
        reg = cls.load()
        canonical = Path(path).resolve().as_posix()
        for entry in reg.projects.values():
            if Path(entry.path).resolve().as_posix() == canonical:
                return entry
        return None
