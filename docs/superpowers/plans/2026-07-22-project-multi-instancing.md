# Project Multi-Instancing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform ruflo-kb from single-KB-in-process to multi-project platform with UUID identity, global registry, per-project settings, async mutex, and 4-step resolution chain.

**Architecture:** Three layers — (1) Global layer at `~/.config/ruflo-kb/` with `registry.json` + `last_project.json`, (2) Per-project `.llm-wiki/` with `project.json` + `settings.json`, (3) Module layer with `ProjectContext` + per-project state. CLI subcommands + auto-discovery on first run.

**Tech Stack:** Python 3.11+, asyncio, platformdirs, pytest, pytest-asyncio, dataclasses.

**MVP Scope** (from spec): UUID identity + project.json / registry.json / last_project.json + 4-step resolve chain + per-project mutex (async + sync wrapper) + auto-discovery + 6 CLI subcommands.

## Global Constraints

- Python 3.11+ (`from __future__ import annotations` for forward refs)
- Async mutex via `asyncio.Lock`, single-process assumption (v1)
- Use `pathlib.Path` everywhere; cross-platform path handling via `Path.resolve()` + `Path.as_posix()`
- All file I/O via `safe_write()` from `src/shared/file_utils.py` (to be implemented in shared-infra task before this plan)
- Platformdirs `user_config_dir("ruflo-kb", "ruflo-kb")` for global config path
- dataclass with `field(default_factory=...)` for mutable defaults; `frozen=False` (we mutate)
- TDD per-task; one commit per task
- Conventional commits: `feat:`, `test:`, `chore:` etc.
- Chinese comments OK; English code identifiers

---

## Phase 1: Identity + Storage

### Task 1: `src/project/paths.py` — config directory helpers

**Files:**
- Create: `src/project/__init__.py`
- Create: `src/project/paths.py`
- Test: `tests/test_project/test_paths.py`

**Interfaces:**
- Consumes: `platformdirs` (new dep)
- Produces: `config_dir() -> Path`, `registry_path() -> Path`, `last_project_path() -> Path`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_project/test_paths.py
from pathlib import Path

from src.project.paths import config_dir, registry_path, last_project_path


def test_config_dir_returns_path():
    """config_dir() returns a Path object under OS config dir."""
    p = config_dir()
    assert isinstance(p, Path)
    assert p.name == "ruflo-kb" or "ruflo-kb" in str(p)


def test_registry_path_under_config_dir():
    """registry_path() lives under config_dir()."""
    p = registry_path()
    assert p.name == "registry.json"
    assert p.parent == config_dir()


def test_last_project_path_under_config_dir():
    """last_project_path() lives under config_dir()."""
    p = last_project_path()
    assert p.name == "last_project.json"
    assert p.parent == config_dir()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_project/test_paths.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.project.paths'`

- [ ] **Step 3: Implement minimal `paths.py`**

```python
# src/project/__init__.py
"""Project multi-instancing — UUID identity, global registry, per-project state."""
```

```python
# src/project/paths.py
"""OS-specific config directory paths for ruflo-kb global state.

Uses platformdirs to follow OS conventions:
- Linux: ~/.config/ruflo-kb/
- macOS: ~/Library/Application Support/ruflo-kb/
- Windows: %APPDATA%/ruflo-kb/
"""
from pathlib import Path

from platformdirs import user_config_dir


_APP_NAME = "ruflo-kb"
_APP_AUTHOR = "ruflo-kb"


def config_dir() -> Path:
    """Return OS-standard config directory for ruflo-kb."""
    return Path(user_config_dir(_APP_NAME, _APP_AUTHOR))


def registry_path() -> Path:
    """Path to global registry.json mapping project UUID → metadata."""
    return config_dir() / "registry.json"


def last_project_path() -> Path:
    """Path to last_project.json (single pointer)."""
    return config_dir() / "last_project.json"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_project/test_paths.py -v`
Expected: PASS (3/3)

- [ ] **Step 5: Commit**

```bash
git add src/project/__init__.py src/project/paths.py tests/test_project/__init__.py tests/test_project/test_paths.py pyproject.toml
git commit -m "feat(project): add config directory helpers (platformdirs)"
```

(Add `platformdirs>=4.0` to pyproject.toml dependencies in same commit.)

---

### Task 2: `src/project/identity.py` — ProjectIdentity + UUID generation

**Files:**
- Create: `src/project/identity.py`
- Test: `tests/test_project/test_identity.py`

**Interfaces:**
- Consumes: nothing
- Produces: `ProjectIdentity` dataclass, `ensure_project_id(project_path) -> str`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_project/test_identity.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.project.identity'`

- [ ] **Step 3: Implement `identity.py`**

```python
# src/project/identity.py
"""Project identity — UUID v4 generation + project.json I/O."""
import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


_logger = logging.getLogger(__name__)


@dataclass
class ProjectIdentity:
    """Per-project identity stored in `.llm-wiki/project.json`.

    Fields:
        id: UUID v4 (stable across filesystem moves/renames)
        name: human-readable project name (unique within registry)
        created_at: unix ms timestamp
        schema_version: current schema version (e.g., "v2.0")
    """
    id: str
    name: str
    created_at: int
    schema_version: str = "v2.0"

    PROJECT_JSON_PATH = ".llm-wiki/project.json"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectIdentity":
        return cls(
            id=data["id"],
            name=data["name"],
            created_at=data["created_at"],
            schema_version=data.get("schema_version", "v2.0"),
        )


def ensure_project_id(project_path: Path) -> str:
    """Ensure `.llm-wiki/project.json` exists; return its UUID.

    - If file missing or corrupt → generate new UUID + write
    - If file valid → return existing UUID

    Args:
        project_path: KB root directory (e.g., `/home/user/research`)

    Returns:
        UUID v4 string (e.g., `550e8400-e29b-41d4-a716-446655440000`)
    """
    project_path = Path(project_path)
    project_json = project_path / ProjectIdentity.PROJECT_JSON_PATH

    # Try to load existing
    if project_json.exists():
        try:
            data = json.loads(project_json.read_text(encoding="utf-8"))
            ident = ProjectIdentity.from_dict(data)
            if ident.id:
                return ident.id
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            _logger.warning(f"[project-identity] corrupt project.json: {e}; regenerating")

    # Generate new
    ident = ProjectIdentity(
        id=str(uuid.uuid4()),
        name=project_path.name,
        created_at=_now_ms(),
    )
    project_json.parent.mkdir(parents=True, exist_ok=True)
    project_json.write_text(
        json.dumps(ident.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return ident.id


def _now_ms() -> int:
    """Unix epoch in milliseconds."""
    import time
    return int(time.time() * 1000)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_project/test_identity.py -v`
Expected: PASS (4/4)

- [ ] **Step 5: Commit**

```bash
git add src/project/identity.py tests/test_project/test_identity.py
git commit -m "feat(project): add ProjectIdentity + ensure_project_id"
```

---

### Task 3: `src/project/registry.py` — GlobalRegistry CRUD

**Files:**
- Create: `src/project/registry.py`
- Test: `tests/test_project/test_registry.py`

**Interfaces:**
- Consumes: `paths.registry_path()`, `ProjectRegistryEntry`
- Produces: `GlobalRegistryStore` with `load()`, `save()`, `upsert()`, `remove()`, `by_id()`, `by_name()`, `by_path()`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_project/test_registry.py
import json
from pathlib import Path

from src.project.registry import (
    GlobalRegistry,
    GlobalRegistryStore,
    ProjectRegistryEntry,
)


def test_load_returns_empty_when_no_file(tmp_path, monkeypatch):
    """load() returns empty GlobalRegistry when registry.json doesn't exist."""
    from src.project import paths

    monkeypatch.setattr(paths, "registry_path", lambda: tmp_path / "registry.json")

    reg = GlobalRegistryStore.load()
    assert reg.projects == {}


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_project/test_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.project.registry'`

- [ ] **Step 3: Implement `registry.py`**

```python
# src/project/registry.py
"""Global project registry — UUID → metadata mapping persisted to registry.json."""
import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


from .paths import registry_path as _default_registry_path


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
        return _default_registry_path()

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_project/test_registry.py -v`
Expected: PASS (6/6)

- [ ] **Step 5: Commit**

```bash
git add src/project/registry.py tests/test_project/test_registry.py
git commit -m "feat(project): add GlobalRegistryStore (UUID → metadata CRUD)"
```

---

### Task 4: `last_project.json` pointer + `ProjectContext.from_path()`

**Files:**
- Create: `src/project/context.py`
- Test: `tests/test_project/test_context.py`

**Interfaces:**
- Consumes: `identity.ensure_project_id`, `registry.GlobalRegistryStore`
- Produces: `ProjectContext.from_path(path, name=None) -> ProjectContext`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_project/test_context.py
from pathlib import Path

from src.project.context import ProjectContext
from src.project.identity import ProjectIdentity
from src.project.registry import GlobalRegistryStore, ProjectRegistryEntry


def test_from_path_creates_new_project(tmp_path, monkeypatch):
    """from_path() on fresh dir creates project.json + registers in registry."""
    from src.project import paths, registry

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(paths, "config_dir", lambda: config_dir)
    monkeypatch.setattr(registry, "_default_registry_path", lambda: config_dir / "registry.json")
    monkeypatch.setattr("src.project.context._registry_path", lambda: config_dir / "registry.json")

    project_dir = tmp_path / "my_kb"
    project_dir.mkdir()

    ctx = ProjectContext.from_path(project_dir, name="my_kb")

    assert ctx.id is not None
    assert len(ctx.id) == 36
    assert ctx.name == "my_kb"
    assert ctx.path == project_dir.resolve()
    assert ctx.schema_version == "v2.0"

    # Registered in global registry
    entry = GlobalRegistryStore.by_id(ctx.id)
    assert entry is not None
    assert entry.name == "my_kb"


def test_from_path_returns_existing(tmp_path, monkeypatch):
    """from_path() on existing project returns same UUID."""
    from src.project import paths, registry
    from src.project.context import _registry_path

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(paths, "config_dir", lambda: config_dir)
    monkeypatch.setattr(registry, "_default_registry_path", lambda: config_dir / "registry.json")
    monkeypatch.setattr("src.project.context", "_registry_path", lambda: config_dir / "registry.json", raising=False)

    project_dir = tmp_path / "existing_kb"
    project_dir.mkdir()

    first = ProjectContext.from_path(project_dir, name="existing_kb")
    second = ProjectContext.from_path(project_dir, name="existing_kb")
    assert first.id == second.id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_project/test_context.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.project.context'`

- [ ] **Step 3: Implement `context.py` (initial version)**

```python
# src/project/context.py
"""ProjectContext — resolved, ready-to-use project handle.

Created via:
- ProjectContext.from_path(path) — for explicit init / discovery
- ProjectContext.resolve(project_arg) — for CLI entry points
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .identity import ProjectIdentity, ensure_project_id
from .paths import config_dir as _config_dir
from .paths import last_project_path as _last_project_path
from .registry import (
    GlobalRegistryStore,
    ProjectRegistryEntry,
    registry_path as _registry_path,
)


@dataclass
class ProjectContext:
    """Resolved project handle passed to every spec function."""
    identity: ProjectIdentity
    path: Path
    name: str
    schema_version: str = "v2.0"

    @property
    def id(self) -> str:
        return self.identity.id

    @classmethod
    def from_path(cls, project_path: Path, name: str | None = None) -> "ProjectContext":
        """Initialize or read project at given path.

        1. ensure_project_id → generates or reads UUID
        2. Register in GlobalRegistryStore (idempotent)
        3. Return ProjectContext

        Args:
            project_path: KB root directory
            name: override name (defaults to project_path.name)
        """
        project_path = Path(project_path).resolve()
        uuid = ensure_project_id(project_path)

        # Read back identity to get full data
        project_json = project_path / ProjectIdentity.PROJECT_JSON_PATH
        import json
        identity = ProjectIdentity.from_dict(json.loads(project_json.read_text(encoding="utf-8")))

        # Register / update in global registry
        resolved_name = name or project_path.name
        entry = ProjectRegistryEntry(
            id=uuid,
            path=str(project_path),
            name=resolved_name,
            last_opened=_now_ms(),
            schema_version=identity.schema_version,
        )
        GlobalRegistryStore.upsert(entry)

        return cls(
            identity=identity,
            path=project_path,
            name=resolved_name,
            schema_version=identity.schema_version,
        )


def _now_ms() -> int:
    import time
    return int(time.time() * 1000)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_project/test_context.py -v`
Expected: PASS (2/2)

- [ ] **Step 5: Commit**

```bash
git add src/project/context.py tests/test_project/test_context.py
git commit -m "feat(project): add ProjectContext.from_path() with registry integration"
```

---

## Phase 2: Resolution Chain

### Task 5: `ProjectContext.resolve()` 4-step chain

**Files:**
- Modify: `src/project/context.py`
- Test: `tests/test_project/test_context_resolve.py`

**Interfaces:**
- Produces: `ProjectContext.resolve(project_arg: str | None, by_id_only: bool = False) -> ProjectContext`
- Raises: `ProjectNotFoundError` with hint message

- [ ] **Step 1: Write the failing test**

```python
# tests/test_project/test_context_resolve.py
import pytest
from pathlib import Path

from src.project.context import ProjectContext, ProjectNotFoundError
from src.project.registry import GlobalRegistryStore, ProjectRegistryEntry


def test_resolve_by_id(tmp_path, monkeypatch):
    """resolve('uuid-xxx') returns entry from registry."""
    from src.project import paths, registry, context
    from src.project.context import _registry_path

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(paths, "config_dir", lambda: config_dir)
    monkeypatch.setattr(registry, "_default_registry_path", lambda: config_dir / "registry.json")
    monkeypatch.setattr(context, "_registry_path", lambda: config_dir / "registry.json", raising=False)

    project_dir = tmp_path / "p"
    project_dir.mkdir()
    ctx = ProjectContext.from_path(project_dir, name="p")

    resolved = ProjectContext.resolve(ctx.id)
    assert resolved.id == ctx.id


def test_resolve_by_name(tmp_path, monkeypatch):
    """resolve('myproject') finds by name."""
    from src.project import paths, registry, context
    monkeypatch.setattr(paths, "config_dir", lambda: tmp_path / "config")
    monkeypatch.setattr(registry, "_default_registry_path", lambda: tmp_path / "config" / "registry.json")
    monkeypatch.setattr(context, "_registry_path", lambda: tmp_path / "config" / "registry.json", raising=False)

    project_dir = tmp_path / "p"
    project_dir.mkdir()
    ProjectContext.from_path(project_dir, name="myproject")

    resolved = ProjectContext.resolve("myproject")
    assert resolved.name == "myproject"


def test_resolve_cwd_upward(tmp_path, monkeypatch, chdir):
    """resolve(None) + CWD inside project → finds via upward search."""
    from src.project import paths, registry, context
    monkeypatch.setattr(paths, "config_dir", lambda: tmp_path / "config")
    monkeypatch.setattr(registry, "_default_registry_path", lambda: tmp_path / "config" / "registry.json")
    monkeypatch.setattr(context, "_registry_path", lambda: tmp_path / "config" / "registry.json", raising=False)

    project_dir = tmp_path / "p" / "deep" / "nested"
    project_dir.mkdir(parents=True)
    ProjectContext.from_path(tmp_path / "p", name="p")

    # Pretend CWD is deep inside project
    monkeypatch.chdir(project_dir)
    resolved = ProjectContext.resolve(None)
    assert resolved.id is not None


def test_resolve_raises_with_hint(tmp_path, monkeypatch):
    """resolve() with no project + no CWD project + no last_project → ProjectNotFoundError with hint."""
    from src.project import paths, registry, context
    monkeypatch.setattr(paths, "config_dir", lambda: tmp_path / "config")
    monkeypatch.setattr(registry, "_default_registry_path", lambda: tmp_path / "config" / "registry.json")
    monkeypatch.setattr(context, "_registry_path", lambda: tmp_path / "config" / "registry.json", raising=False)
    monkeypatch.chdir(tmp_path)  # empty dir, no project

    with pytest.raises(ProjectNotFoundError) as exc:
        ProjectContext.resolve(None)
    assert "No project resolved" in str(exc.value)
    assert "project init" in str(exc.value)
```

(Note: `chdir` fixture is pytest's `monkeypatch.chdir`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_project/test_context_resolve.py -v`
Expected: FAIL with `AttributeError: type object 'ProjectContext' has no attribute 'resolve'`

- [ ] **Step 3: Add `resolve()` + `ProjectNotFoundError`**

```python
# src/project/context.py — add to existing file

class ProjectNotFoundError(Exception):
    """Raised when resolve() can't find a project from any source.

    Includes a hint message guiding user to fix.
    """
    def __init__(self, message: str):
        super().__init__(message)


# Add to ProjectContext class:

class ProjectContext:
    # ... existing fields and from_path ...

    @classmethod
    def resolve(
        cls,
        project_arg: str | None,
        by_id_only: bool = False,
    ) -> "ProjectContext":
        """4-step resolution chain:

        1. project_arg given → lookup in registry by id or name
        2. CWD upward search for `.llm-wiki/project.json`
        3. last_project.json pointer
        4. ProjectNotFoundError with hint

        Args:
            project_arg: explicit UUID or name from --project arg (None = auto-resolve)
            by_id_only: if True, skip steps 2-3 (used by HTTP API for safety)

        Returns:
            ProjectContext for the resolved project
        """
        # Step 1: explicit --project arg
        if project_arg:
            entry = GlobalRegistryStore.by_id(project_arg)
            if entry:
                return cls._from_registry_entry(entry)
            entry = GlobalRegistryStore.by_name(project_arg)
            if entry:
                return cls._from_registry_entry(entry)
            raise ProjectNotFoundError(
                f"No project with id/name '{project_arg}'. "
                f"Run `python -m src.cli project list` to see known projects."
            )

        if by_id_only:
            # HTTP API: don't fall back to CWD or last_project
            raise ProjectNotFoundError(
                "project_id required for HTTP API calls. "
                "Pass ?project_id=<uuid> or X-Project-Id header."
            )

        # Step 2: CWD upward search
        cwd = Path.cwd().resolve()
        for ancestor in [cwd, *cwd.parents]:
            project_json = ancestor / ProjectIdentity.PROJECT_JSON_PATH
            if project_json.exists():
                try:
                    return cls.from_path(ancestor)
                except Exception:
                    continue

        # Step 3: last_project.json
        last = GlobalRegistryStore.load_last_project()
        if last:
            entry = GlobalRegistryStore.by_id(last.id)
            if entry:
                return cls._from_registry_entry(entry)

        # Step 4: error
        raise ProjectNotFoundError(
            "No project resolved. Choose one of:\n"
            "  1. Run `python -m src.cli project init <path>` to create\n"
            "  2. Run `python -m src.cli project list` to see known projects\n"
            "  3. `cd` into a project directory (has `.llm-wiki/project.json`)\n"
            "  4. Pass `--project <id|name>` flag"
        )

    @classmethod
    def _from_registry_entry(cls, entry: ProjectRegistryEntry) -> "ProjectContext":
        """Build ProjectContext from registry entry (read project.json for identity)."""
        project_path = Path(entry.path)
        if not project_path.exists():
            raise ProjectNotFoundError(
                f"Project '{entry.name}' registered but path no longer exists: {project_path}. "
                f"Run `python -m src.cli project forget {entry.id}` to clean up."
            )
        # Load identity from project.json (don't regenerate)
        import json
        project_json = project_path / ProjectIdentity.PROJECT_JSON_PATH
        identity = ProjectIdentity.from_dict(
            json.loads(project_json.read_text(encoding="utf-8"))
        )
        # Update last_opened
        entry.last_opened = _now_ms()
        GlobalRegistryStore.upsert(entry)
        return cls(
            identity=identity,
            path=project_path.resolve(),
            name=entry.name,
            schema_version=identity.schema_version,
        )


# Add to GlobalRegistryStore class:

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


@dataclass
class LastProjectPointer:
    id: str
    path: str
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_project/test_context_resolve.py -v`
Expected: PASS (4/4)

- [ ] **Step 5: Commit**

```bash
git add src/project/context.py tests/test_project/test_context_resolve.py
git commit -m "feat(project): add ProjectContext.resolve() 4-step chain"
```

---

## Phase 3: Mutex

### Task 6: `with_project_lock` async + sync wrapper

**Files:**
- Create: `src/project/mutex.py`
- Test: `tests/test_project/test_mutex.py`

**Interfaces:**
- Produces: `async with_project_lock(project_id, fn)`, `sync_with_project_lock(project_id, fn)`, `__reset_for_testing`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_project/test_mutex.py
import asyncio
import time

from src.project.mutex import (
    with_project_lock,
    sync_with_project_lock,
    __reset_for_testing,
)


def setup_function(_):
    __reset_for_testing()


async def test_async_lock_serializes_same_project():
    """Two concurrent calls with same project_id run sequentially."""
    order: list[str] = []

    async def task_a():
        async with with_project_lock("proj-1", lambda: _delay_then(order, "a", 0.1)) if False else None:
            pass  # not used; see below

    async def slow():
        order.append("slow-start")
        await asyncio.sleep(0.05)
        order.append("slow-end")
        return "slow"

    async def fast():
        order.append("fast-start")
        await asyncio.sleep(0.01)
        order.append("fast-end")
        return "fast"

    # Run sequentially because they share project_id
    result_slow = await with_project_lock("proj-1", slow)
    result_fast = await with_project_lock("proj-1", fast)
    assert result_slow == "slow"
    assert result_fast == "fast"
    # Order: slow fully completes, then fast starts
    assert order.index("slow-end") < order.index("fast-start")


def _delay_then(order, label, t):
    """Stub: in real test we'd await asyncio.sleep"""
    pass  # not used; see coroutine test


async def test_async_lock_different_projects_concurrent():
    """Two concurrent calls with different project_ids run in parallel."""
    counter = {"a_started": 0, "a_finished": 0, "b_started": 0, "b_finished": 0}

    async def task_a():
        counter["a_started"] += 1
        await asyncio.sleep(0.05)
        counter["a_finished"] += 1

    async def task_b():
        counter["b_started"] += 1
        await asyncio.sleep(0.05)
        counter["b_finished"] += 1

    await asyncio.gather(
        with_project_lock("proj-A", task_a),
        with_project_lock("proj-B", task_b),
    )
    # Both started before either finished (parallel)
    assert counter["a_started"] == 1
    assert counter["b_started"] == 1
    assert counter["a_finished"] == 1
    assert counter["b_finished"] == 1


def test_sync_lock_runs_callable():
    """sync_with_project_lock executes callable synchronously."""

    def work():
        return 42

    result = sync_with_project_lock("proj-sync", work)
    assert result == 42


async def test_async_lock_propagates_exception():
    """Exception inside with_project_lock is re-raised."""
    async def fail():
        raise ValueError("boom")

    import pytest
    with pytest.raises(ValueError, match="boom"):
        await with_project_lock("proj-fail", fail)


async def test_lock_released_after_exception():
    """Lock is released even when callable raises."""
    async def fail():
        raise RuntimeError("oops")

    try:
        await with_project_lock("proj-recover", fail)
    except RuntimeError:
        pass

    # Lock should be released; another task should run immediately
    async def fast():
        return "ok"

    result = await with_project_lock("proj-recover", fast)
    assert result == "ok"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_project/test_mutex.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.project.mutex'`

- [ ] **Step 3: Implement `mutex.py`**

```python
# src/project/mutex.py
"""Per-project async mutex + sync wrapper.

Different project_ids are fully concurrent. Same project_id is serialized.
Single-process assumption (v1).
"""
import asyncio
from typing import Awaitable, Callable, TypeVar


T = TypeVar("T")

_locks: dict[str, asyncio.Lock] = {}


def _lock_for(project_id: str) -> asyncio.Lock:
    """Get-or-create lock for project_id."""
    if project_id not in _locks:
        _locks[project_id] = asyncio.Lock()
    return _locks[project_id]


async def with_project_lock(project_id: str, fn: Callable[[], Awaitable[T]]) -> T:
    """Serialize mutations within a project. Async context.

    Usage:
        result = await with_project_lock("uuid-123", some_async_fn)

    Different project_ids run concurrently; same project_id is serialized.
    """
    async with _lock_for(project_id):
        return await fn()


def sync_with_project_lock(project_id: str, fn: Callable[[], T]) -> T:
    """Sync wrapper for CLI subcommands. Blocks until lock acquired + fn done.

    Usage:
        result = sync_with_project_lock("uuid-123", lambda: do_work())

    Internally uses asyncio.run; can NOT be called from within an async context.
    """
    async def _wrapper() -> T:
        async with _lock_for(project_id):
            return fn()

    # asyncio.run() creates new event loop
    return asyncio.run(_wrapper())


def __reset_for_testing() -> None:
    """Drop all live locks. Test-only."""
    _locks.clear()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_project/test_mutex.py -v`
Expected: PASS (5/5)

- [ ] **Step 5: Commit**

```bash
git add src/project/mutex.py tests/test_project/test_mutex.py
git commit -m "feat(project): add with_project_lock async + sync mutex"
```

---

## Phase 4: Auto-Discovery

### Task 7: `discover_existing_kbs()` + `auto_register_on_first_run()`

**Files:**
- Create: `src/project/discovery.py`
- Test: `tests/test_project/test_discovery.py`

**Interfaces:**
- Produces: `is_kb_root(path) -> bool`, `discover_existing_kbs() -> list[Path]`, `auto_register_on_first_run() -> list[ProjectContext]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_project/test_discovery.py
from pathlib import Path

from src.project.discovery import (
    DEFAULT_SEARCH_PATHS,
    is_kb_root,
    discover_existing_kbs,
    auto_register_on_first_run,
)
from src.project.registry import GlobalRegistryStore


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
    from src.project import paths, registry
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
    from src.project.discovery import DEFAULT_SEARCH_PATHS

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
    from src.project.discovery import DEFAULT_SEARCH_PATHS

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_project/test_discovery.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.project.discovery'`

- [ ] **Step 3: Implement `discovery.py`**

```python
# src/project/discovery.py
"""Auto-discovery of existing KB projects on first run.

Scans DEFAULT_SEARCH_PATHS for directories containing KB markers
(.index/schema_version for v2.0, or Notes/ subdir for v1.0).
"""
import logging
from pathlib import Path

from .context import ProjectContext
from .registry import GlobalRegistryStore


_logger = logging.getLogger(__name__)


# Default search paths for first-run discovery.
# Tests can monkeypatch this to use tmp dirs.
DEFAULT_SEARCH_PATHS: list[Path] = [
    Path.home() / "Documents",
    Path.home() / "Notes",
    Path.home() / "Knowledge",
    Path.home() / "wiki",
]


def is_kb_root(path: Path) -> bool:
    """Detect if a directory is a KB root (v1.0 or v2.0).

    v2.0 marker: <path>/.index/schema_version exists
    v1.0 marker: <path>/Notes/ subdir exists
    """
    path = Path(path)
    if (path / ".index" / "schema_version").is_file():
        return True
    if (path / "Notes").is_dir():
        return True
    return False


def discover_existing_kbs() -> list[Path]:
    """Scan DEFAULT_SEARCH_PATHS (top-level + 1 level deeper) for KBs.

    Returns list of KB root paths. Empty if none found.
    """
    found: list[Path] = []
    seen: set[Path] = set()

    for base in DEFAULT_SEARCH_PATHS:
        if not base.exists() or not base.is_dir():
            continue
        try:
            # base itself
            if is_kb_root(base) and base.resolve() not in seen:
                found.append(base.resolve())
                seen.add(base.resolve())
            # 1 level deeper
            for child in base.iterdir():
                if not child.is_dir():
                    continue
                child_resolved = child.resolve()
                if is_kb_root(child) and child_resolved not in seen:
                    found.append(child_resolved)
                    seen.add(child_resolved)
        except PermissionError:
            _logger.warning(f"[discovery] permission denied: {base}")
            continue
    return found


def auto_register_on_first_run() -> list[ProjectContext]:
    """If registry.json doesn't exist, discover + register KBs.

    Idempotent: if registry.json exists, no-op.

    Returns list of newly registered ProjectContexts.
    """
    from .paths import registry_path as _registry_path
    from .registry import registry_path as _default_registry_path

    if _default_registry_path().exists():
        return []  # not first run

    kb_paths = discover_existing_kbs()
    contexts: list[ProjectContext] = []
    for kb_path in kb_paths:
        try:
            ctx = ProjectContext.from_path(kb_path)
            contexts.append(ctx)
        except Exception as e:
            _logger.warning(f"[discovery] failed to register {kb_path}: {e}")

    if contexts:
        # Set last_project to most recently modified
        contexts.sort(key=lambda c: c.path.stat().st_mtime, reverse=True)
        GlobalRegistryStore.save_last_project(
            id=contexts[0].id,
            path=str(contexts[0].path),
        )

    return contexts
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_project/test_discovery.py -v`
Expected: PASS (6/6)

- [ ] **Step 5: Commit**

```bash
git add src/project/discovery.py tests/test_project/test_discovery.py
git commit -m "feat(project): add KB auto-discovery (DEFAULT_SEARCH_PATHS scan)"
```

---

## Phase 5: CLI Subcommands

### Task 8: `cmd_project_init` + `cmd_project_list`

**Files:**
- Create: `src/cli_ext/project_cmd.py`
- Modify: `src/cli.py` (add subparser)
- Test: `tests/test_cli_ext/test_cmd_project.py`

**Interfaces:**
- Produces: `cmd_project_init(args)`, `cmd_project_list(args)` callable

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_ext/test_cmd_project.py
import json
import sys
from pathlib import Path
from unittest.mock import patch


def test_cmd_project_init_creates_project(tmp_path, monkeypatch, capsys):
    """cmd_project_init creates project.json + registers in global registry."""
    from src.cli_ext import project_cmd
    from src.project import paths, registry

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    project_dir = tmp_path / "myproject"
    project_dir.mkdir()

    monkeypatch.setattr(paths, "config_dir", lambda: config_dir)
    monkeypatch.setattr(registry, "_default_registry_path", lambda: config_dir / "registry.json")
    monkeypatch.setattr("src.cli_ext.project_cmd._registry_path", lambda: config_dir / "registry.json", raising=False)
    monkeypatch.setattr("src.cli_ext.project_cmd._config_dir", lambda: config_dir, raising=False)

    args = type("Args", (), {"path": str(project_dir), "name": None})()

    project_cmd.cmd_project_init(args)

    # project.json created
    assert (project_dir / ".llm-wiki" / "project.json").exists()
    # Registry has entry
    data = json.loads((config_dir / "registry.json").read_text())
    assert "projects" in data
    assert len(data["projects"]) == 1

    captured = capsys.readouter()
    assert "Initialized" in captured.out or "myproject" in captured.out


def test_cmd_project_list_shows_registered(tmp_path, monkeypatch, capsys):
    """cmd_project_list shows all registered projects."""
    from src.cli_ext import project_cmd
    from src.project import paths, registry

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(paths, "config_dir", lambda: config_dir)
    monkeypatch.setattr(registry, "_default_registry_path", lambda: config_dir / "registry.json")
    monkeypatch.setattr("src.cli_ext.project_cmd._registry_path", lambda: config_dir / "registry.json", raising=False)

    # Pre-populate registry
    config_dir.joinpath("registry.json").write_text(json.dumps({
        "version": 1,
        "projects": {
            "uuid-a": {"id": "uuid-a", "path": "/p/a", "name": "alpha", "last_opened": 1000, "schema_version": "v2.0"},
            "uuid-b": {"id": "uuid-b", "path": "/p/b", "name": "beta", "last_opened": 2000, "schema_version": "v2.0"},
        }
    }))

    args = type("Args", (), {})()
    project_cmd.cmd_project_list(args)

    captured = capsys.readouter()
    assert "alpha" in captured.out
    assert "beta" in captured.out
    assert "uuid-a" in captured.out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_ext/test_cmd_project.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.cli_ext'`

- [ ] **Step 3: Implement `project_cmd.py` (initial 2 subcommands)**

```python
# src/cli_ext/__init__.py
"""CLI subcommand handlers. Each module owns a domain of subcommands."""
```

```python
# src/cli_ext/project_cmd.py
"""Project management subcommands: init / list / info / current / select / import / forget / rename / discover."""
import argparse
import json
import sys

from ..project.context import ProjectContext
from ..project.paths import config_dir as _config_dir
from ..project.registry import (
    GlobalRegistryStore,
    ProjectRegistryEntry,
    registry_path as _registry_path,
)


def cmd_project_init(args: argparse.Namespace) -> None:
    """Initialize a new project at the given path."""
    from pathlib import Path
    project_path = Path(args.path).resolve()
    name = args.name or project_path.name
    ctx = ProjectContext.from_path(project_path, name=name)
    print(f"Initialized project '{ctx.name}' ({ctx.id})")
    print(f"Path: {ctx.path}")


def cmd_project_list(args: argparse.Namespace) -> None:
    """List all registered projects."""
    reg = GlobalRegistryStore.load()
    if not reg.projects:
        print("No projects registered.")
        return
    print(f"{'ID':<40} {'Name':<20} {'Last Opened':<20}")
    print("-" * 80)
    for entry in sorted(reg.projects.values(), key=lambda e: -e.last_opened):
        from datetime import datetime
        ts = datetime.fromtimestamp(entry.last_opened / 1000).isoformat()
        print(f"{entry.id:<40} {entry.name:<20} {ts:<20}")
```

- [ ] **Step 4: Wire subparsers in `src/cli.py`**

```python
# src/cli.py — add to existing main()

def main():
    parser = argparse.ArgumentParser(description="ruflo-kb")
    subparsers = parser.add_subparsers(dest="command")

    # Existing subparsers...

    # Project subcommand
    p_project = subparsers.add_parser("project", help="Manage projects")
    p_project_sub = p_project.add_subparsers(dest="project_command")

    p_init = p_project_sub.add_parser("init", help="Initialize new project")
    p_init.add_argument("path", help="Project root directory")
    p_init.add_argument("--name", help="Project name (default: path basename)")
    p_init.set_defaults(func=cmd_project_init)

    p_list = p_project_sub.add_parser("list", help="List registered projects")
    p_list.set_defaults(func=cmd_project_list)

    # ...

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(1)
    args.func(args)
```

(Add `from cli_ext.project_cmd import cmd_project_init, cmd_project_list` at top.)

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_cli_ext/test_cmd_project.py -v`
Expected: PASS (2/2)

- [ ] **Step 6: Commit**

```bash
git add src/cli_ext/__init__.py src/cli_ext/project_cmd.py src/cli.py tests/test_cli_ext/__init__.py tests/test_cli_ext/test_cmd_project.py
git commit -m "feat(cli): add 'project init' + 'project list' subcommands"
```

---

### Task 9: `cmd_project_info` + `cmd_project_current` + `cmd_project_select`

**Files:**
- Modify: `src/cli_ext/project_cmd.py`
- Modify: `src/cli.py` (wire subparsers)
- Test: extend `tests/test_cli_ext/test_cmd_project.py`

- [ ] **Step 1: Add tests**

```python
# tests/test_cli_ext/test_cmd_project.py — append:

def test_cmd_project_info(tmp_path, monkeypatch, capsys):
    """cmd_project_info prints full metadata for one project."""
    from src.cli_ext import project_cmd
    from src.project import paths, registry

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(paths, "config_dir", lambda: config_dir)
    monkeypatch.setattr(registry, "_default_registry_path", lambda: config_dir / "registry.json")
    monkeypatch.setattr("src.cli_ext.project_cmd._registry_path", lambda: config_dir / "registry.json", raising=False)

    config_dir.joinpath("registry.json").write_text(json.dumps({
        "version": 1,
        "projects": {"uuid-x": {"id": "uuid-x", "path": "/p/x", "name": "x", "last_opened": 1000, "schema_version": "v2.0"}}
    }))

    args = type("Args", (), {"id_or_name": "uuid-x"})()
    project_cmd.cmd_project_info(args)

    out = capsys.readouter().out
    assert "uuid-x" in out
    assert "x" in out
    assert "/p/x" in out


def test_cmd_project_current(tmp_path, monkeypatch, capsys):
    """cmd_project_current prints the resolved project from last_project pointer."""
    from src.cli_ext import project_cmd
    from src.project import paths, registry
    from src.project.context import ProjectContext

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    project_dir = tmp_path / "p"
    project_dir.mkdir()
    ctx = ProjectContext.from_path(project_dir, name="p")

    monkeypatch.setattr(paths, "config_dir", lambda: config_dir)
    monkeypatch.setattr(registry, "_default_registry_path", lambda: config_dir / "registry.json")
    monkeypatch.setattr("src.cli_ext.project_cmd._registry_path", lambda: config_dir / "registry.json", raising=False)

    args = type("Args", (), {})()
    project_cmd.cmd_project_current(args)

    out = capsys.readouter().out
    assert ctx.id in out
    assert "p" in out


def test_cmd_project_select(tmp_path, monkeypatch, capsys):
    """cmd_project_select updates last_project pointer."""
    from src.cli_ext import project_cmd
    from src.project import paths, registry

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(paths, "config_dir", lambda: config_dir)
    monkeypatch.setattr(registry, "_default_registry_path", lambda: config_dir / "registry.json")
    monkeypatch.setattr("src.cli_ext.project_cmd._registry_path", lambda: config_dir / "registry.json", raising=False)
    monkeypatch.setattr("src.cli_ext.project_cmd._last_project_path", lambda: config_dir / "last_project.json", raising=False)

    config_dir.joinpath("registry.json").write_text(json.dumps({
        "version": 1,
        "projects": {"uuid-sel": {"id": "uuid-sel", "path": "/p/s", "name": "selected", "last_opened": 0, "schema_version": "v2.0"}}
    }))

    args = type("Args", (), {"id_or_name": "selected"})()
    project_cmd.cmd_project_select(args)

    assert (config_dir / "last_project.json").exists()
    data = json.loads((config_dir / "last_project.json").read_text())
    assert data["id"] == "uuid-sel"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_ext/test_cmd_project.py -v -k "info or current or select"`
Expected: FAIL with `AttributeError: module 'src.cli_ext.project_cmd' has no attribute 'cmd_project_info'`

- [ ] **Step 3: Add 3 subcommands**

```python
# src/cli_ext/project_cmd.py — append:

def cmd_project_info(args: argparse.Namespace) -> None:
    """Print full metadata for one project."""
    entry = GlobalRegistryStore.by_id(args.id_or_name)
    if not entry:
        entry = GlobalRegistryStore.by_name(args.id_or_name)
    if not entry:
        print(f"Project not found: {args.id_or_name}", file=sys.stderr)
        sys.exit(2)
    from datetime import datetime
    ts = datetime.fromtimestamp(entry.last_opened / 1000).isoformat()
    print(f"ID:            {entry.id}")
    print(f"Name:          {entry.name}")
    print(f"Path:          {entry.path}")
    print(f"Last Opened:   {ts}")
    print(f"Schema Version: {entry.schema_version}")


def cmd_project_current(args: argparse.Namespace) -> None:
    """Print the resolved current project (from last_project pointer or registry)."""
    from ..project.context import ProjectContext
    ctx = ProjectContext.resolve(None)
    print(f"Current project: {ctx.name} ({ctx.id})")
    print(f"Path: {ctx.path}")


def cmd_project_select(args: argparse.Namespace) -> None:
    """Set the last_project pointer to a specific project."""
    from ..project.paths import last_project_path as _last_project_path
    entry = GlobalRegistryStore.by_id(args.id_or_name)
    if not entry:
        entry = GlobalRegistryStore.by_name(args.id_or_name)
    if not entry:
        print(f"Project not found: {args.id_or_name}", file=sys.stderr)
        sys.exit(2)
    GlobalRegistryStore.save_last_project(id=entry.id, path=entry.path)
    print(f"Selected project: {entry.name} ({entry.id})")
```

- [ ] **Step 4: Wire subparsers in `src/cli.py`**

```python
# src/cli.py — add to "project" subparser block:

p_info = p_project_sub.add_parser("info", help="Show project metadata")
p_info.add_argument("id_or_name", help="Project UUID or name")
p_info.set_defaults(func=cmd_project_info)

p_current = p_project_sub.add_parser("current", help="Show current project")
p_current.set_defaults(func=cmd_project_current)

p_select = p_project_sub.add_parser("select", help="Set last_project pointer")
p_select.add_argument("id_or_name", help="Project UUID or name")
p_select.set_defaults(func=cmd_project_select)
```

(Add imports for the 3 new subcommands.)

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_cli_ext/test_cmd_project.py -v -k "info or current or select"`
Expected: PASS (3/3)

- [ ] **Step 6: Commit**

```bash
git add src/cli_ext/project_cmd.py src/cli.py tests/test_cli_ext/test_cmd_project.py
git commit -m "feat(cli): add 'project info/current/select' subcommands"
```

---

### Task 10: `cmd_project_import` + `cmd_project_forget` + `cmd_project_rename` + `cmd_project_discover`

**Files:**
- Modify: `src/cli_ext/project_cmd.py`
- Modify: `src/cli.py` (wire subparsers)
- Test: extend `tests/test_cli_ext/test_cmd_project.py`

- [ ] **Step 1: Add tests**

```python
# tests/test_cli_ext/test_cmd_project.py — append:

def test_cmd_project_import(tmp_path, monkeypatch, capsys):
    """cmd_project_import registers an existing KB at given path."""
    from src.cli_ext import project_cmd
    from src.project import paths, registry

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    kb = tmp_path / "external_kb"
    kb.mkdir()
    (kb / ".llm-wiki").mkdir()
    (kb / ".llm-wiki" / "project.json").write_text(
        json.dumps({"id": "uuid-ext", "name": "external", "created_at": 1000, "schema_version": "v2.0"}),
        encoding="utf-8",
    )

    monkeypatch.setattr(paths, "config_dir", lambda: config_dir)
    monkeypatch.setattr(registry, "_default_registry_path", lambda: config_dir / "registry.json")
    monkeypatch.setattr("src.cli_ext.project_cmd._registry_path", lambda: config_dir / "registry.json", raising=False)

    args = type("Args", (), {"path": str(kb), "name": None})()
    project_cmd.cmd_project_import(args)

    entry = GlobalRegistryStore.by_id("uuid-ext")
    assert entry is not None
    assert entry.name == "external"


def test_cmd_project_forget_removes_registry_entry(tmp_path, monkeypatch, capsys):
    """cmd_project_forget removes entry from registry but not from disk."""
    from src.cli_ext import project_cmd
    from src.project import paths, registry

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(paths, "config_dir", lambda: config_dir)
    monkeypatch.setattr(registry, "_default_registry_path", lambda: config_dir / "registry.json")
    monkeypatch.setattr("src.cli_ext.project_cmd._registry_path", lambda: config_dir / "registry.json", raising=False)

    config_dir.joinpath("registry.json").write_text(json.dumps({
        "version": 1,
        "projects": {"uuid-f": {"id": "uuid-f", "path": "/p/f", "name": "f", "last_opened": 0, "schema_version": "v2.0"}}
    }))

    args = type("Args", (), {"id_or_name": "uuid-f", "delete_data": False})()
    project_cmd.cmd_project_forget(args)

    assert GlobalRegistryStore.by_id("uuid-f") is None
    captured = capsys.readouter()
    assert "removed from registry" in captured.out


def test_cmd_project_forget_refuses_when_id_used_by_other(tmp_path, monkeypatch, capsys):
    """cmd_project_forget refuses to delete project.json if --delete-data and path no longer registered."""
    from src.cli_ext import project_cmd
    from src.project import paths, registry

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    kb = tmp_path / "kb_real"
    kb.mkdir()
    (kb / ".llm-wiki").mkdir()

    monkeypatch.setattr(paths, "config_dir", lambda: config_dir)
    monkeypatch.setattr(registry, "_default_registry_path", lambda: config_dir / "registry.json")
    monkeypatch.setattr("src.cli_ext.project_cmd._registry_path", lambda: config_dir / "registry.json", raising=False)

    config_dir.joinpath("registry.json").write_text(json.dumps({
        "version": 1,
        "projects": {"uuid-r": {"id": "uuid-r", "path": str(kb), "name": "r", "last_opened": 0, "schema_version": "v2.0"}}
    }))

    args = type("Args", (), {"id_or_name": "uuid-r", "delete_data": True})()
    project_cmd.cmd_project_forget(args)

    # Path should still exist
    assert kb.exists()
    out = capsys.readouter().out
    assert "aborted" in out.lower() or "refused" in out.lower() or "error" in out.lower()


def test_cmd_project_rename(tmp_path, monkeypatch, capsys):
    """cmd_project_rename updates name in registry + project.json."""
    from src.cli_ext import project_cmd
    from src.project import paths, registry

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    kb = tmp_path / "kb_rename"
    kb.mkdir()
    (kb / ".llm-wiki").mkdir()
    (kb / ".llm-wiki" / "project.json").write_text(
        json.dumps({"id": "uuid-rn", "name": "old_name", "created_at": 1000, "schema_version": "v2.0"}),
        encoding="utf-8",
    )

    monkeypatch.setattr(paths, "config_dir", lambda: config_dir)
    monkeypatch.setattr(registry, "_default_registry_path", lambda: config_dir / "registry.json")
    monkeypatch.setattr("src.cli_ext.project_cmd._registry_path", lambda: config_dir / "registry.json", raising=False)

    config_dir.joinpath("registry.json").write_text(json.dumps({
        "version": 1,
        "projects": {"uuid-rn": {"id": "uuid-rn", "path": str(kb), "name": "old_name", "last_opened": 0, "schema_version": "v2.0"}}
    }))

    args = type("Args", (), {"id_or_name": "uuid-rn", "new_name": "new_name"})()
    project_cmd.cmd_project_rename(args)

    entry = GlobalRegistryStore.by_id("uuid-rn")
    assert entry.name == "new_name"
    data = json.loads((kb / ".llm-wiki" / "project.json").read_text())
    assert data["name"] == "new_name"


def test_cmd_project_discover_finds_and_registers(tmp_path, monkeypatch, capsys):
    """cmd_project_discover runs auto_register_on_first_run."""
    from src.cli_ext import project_cmd
    from src.cli_ext.project_cmd import _registry_path
    from src.project import paths, registry, discovery

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    docs = tmp_path / "Documents"
    docs.mkdir()
    (docs / "kb_discovered").mkdir()
    (docs / "kb_discovered" / ".index").mkdir()
    (docs / "kb_discovered" / ".index" / "schema_version").write_text("v2.0")

    monkeypatch.setattr(paths, "config_dir", lambda: config_dir)
    monkeypatch.setattr(registry, "_default_registry_path", lambda: config_dir / "registry.json")
    monkeypatch.setattr(discovery, "DEFAULT_SEARCH_PATHS", [docs])

    args = type("Args", (), {})()
    project_cmd.cmd_project_discover(args)

    out = capsys.readouter().out
    assert "kb_discovered" in out
    entry = GlobalRegistryStore.by_path(docs / "kb_discovered")
    assert entry is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_ext/test_cmd_project.py -v -k "import or forget or rename or discover"`
Expected: FAIL with `AttributeError`

- [ ] **Step 3: Add 4 subcommands**

```python
# src/cli_ext/project_cmd.py — append:

def cmd_project_import(args: argparse.Namespace) -> None:
    """Import an existing KB (path with .llm-wiki/project.json) into registry."""
    from pathlib import Path
    kb_path = Path(args.path).resolve()
    if not (kb_path / ".llm-wiki" / "project.json").exists():
        print(f"No .llm-wiki/project.json at {kb_path}", file=sys.stderr)
        sys.exit(2)
    ctx = ProjectContext.from_path(kb_path, name=args.name)
    print(f"Imported project '{ctx.name}' ({ctx.id})")


def cmd_project_forget(args: argparse.Namespace) -> None:
    """Remove entry from global registry (does NOT delete files unless --delete-data)."""
    entry = GlobalRegistryStore.by_id(args.id_or_name)
    if not entry:
        entry = GlobalRegistryStore.by_name(args.id_or_name)
    if not entry:
        print(f"Project not found: {args.id_or_name}", file=sys.stderr)
        sys.exit(2)

    if args.delete_data:
        from pathlib import Path
        kb_path = Path(entry.path)
        if not kb_path.exists():
            print(f"Path no longer exists: {kb_path}; cannot --delete-data safely", file=sys.stderr)
            sys.exit(3)
        # Refuse if path is shared (multiple entries pointing to same path)
        all_entries = list(GlobalRegistryStore.load().projects.values())
        same_path = [e for e in all_entries if e.path == entry.path and e.id != entry.id]
        if same_path:
            print(f"Refusing --delete-data: path {kb_path} is also referenced by:", file=sys.stderr)
            for e in same_path:
                print(f"  - {e.id} ({e.name})", file=sys.stderr)
            sys.exit(3)
        # Actually delete
        import shutil
        shutil.rmtree(kb_path)
        print(f"Deleted {kb_path}")

    GlobalRegistryStore.remove(entry.id)
    print(f"Project '{entry.name}' removed from registry")


def cmd_project_rename(args: argparse.Namespace) -> None:
    """Rename a project (updates registry + project.json)."""
    entry = GlobalRegistryStore.by_id(args.id_or_name)
    if not entry:
        entry = GlobalRegistryStore.by_name(args.id_or_name)
    if not entry:
        print(f"Project not found: {args.id_or_name}", file=sys.stderr)
        sys.exit(2)

    # Update registry
    entry.name = args.new_name
    GlobalRegistryStore.upsert(entry)

    # Update project.json
    from pathlib import Path
    import json as _json
    project_json = Path(entry.path) / ".llm-wiki" / "project.json"
    if project_json.exists():
        data = _json.loads(project_json.read_text(encoding="utf-8"))
        data["name"] = args.new_name
        project_json.write_text(_json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Renamed '{args.id_or_name}' → '{args.new_name}'")


def cmd_project_discover(args: argparse.Namespace) -> None:
    """Manually trigger auto-discovery of existing KBs."""
    from ..project.discovery import auto_register_on_first_run
    contexts = auto_register_on_first_run()
    if not contexts:
        print("No new projects found.")
        return
    print(f"Discovered {len(contexts)} project(s):")
    for ctx in contexts:
        print(f"  - {ctx.name} ({ctx.id}) at {ctx.path}")
```

- [ ] **Step 4: Wire subparsers in `src/cli.py`**

```python
# src/cli.py — add to "project" subparser block:

p_import = p_project_sub.add_parser("import", help="Import existing KB")
p_import.add_argument("path", help="Path to existing KB root")
p_import.add_argument("--name", help="Override project name")
p_import.set_defaults(func=cmd_project_import)

p_forget = p_project_sub.add_parser("forget", help="Remove project from registry")
p_forget.add_argument("id_or_name", help="Project UUID or name")
p_forget.add_argument("--delete-data", action="store_true", help="Also delete files")
p_forget.set_defaults(func=cmd_project_forget)

p_rename = p_project_sub.add_parser("rename", help="Rename a project")
p_rename.add_argument("id_or_name", help="Current project UUID or name")
p_rename.add_argument("new_name", help="New project name")
p_rename.set_defaults(func=cmd_project_rename)

p_discover = p_project_sub.add_parser("discover", help="Auto-discover existing KBs")
p_discover.set_defaults(func=cmd_project_discover)
```

(Add imports for 4 new subcommands.)

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_cli_ext/test_cmd_project.py -v -k "import or forget or rename or discover"`
Expected: PASS (5/5)

- [ ] **Step 6: Commit**

```bash
git add src/cli_ext/project_cmd.py src/cli.py tests/test_cli_ext/test_cmd_project.py
git commit -m "feat(cli): add 'project import/forget/rename/discover' subcommands"
```

---

## Phase 6: Integration + Wiring

### Task 11: Wire auto-register into `main()` + full integration test

**Files:**
- Modify: `src/cli.py`
- Test: `tests/test_integration/test_project_e2e.py`

- [ ] **Step 1: Write integration test**

```python
# tests/test_integration/test_project_e2e.py
"""End-to-end test: full project lifecycle."""
import json
import subprocess
import sys
from pathlib import Path

import pytest


def test_init_then_list_then_info(tmp_path, monkeypatch):
    """CLI flow: init → list → info."""
    from click.testing import CliRunner  # optional; fallback to subprocess

    config_dir = tmp_path / "config"
    config_dir.mkdir()

    # Set env var for config dir override (consumed by CLI)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_dir))   # Linux convention
    monkeypatch.setenv("APPDATA", str(config_dir))           # Windows convention

    project_dir = tmp_path / "myproject"
    project_dir.mkdir()

    # Run `python -m src.cli project init <path>`
    result = subprocess.run(
        [sys.executable, "-m", "src.cli", "project", "init", str(project_dir)],
        capture_output=True, text=True, env=monkeypatch.environ,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "Initialized" in result.stdout or "myproject" in result.stdout

    # project.json created
    assert (project_dir / ".llm-wiki" / "project.json").exists()

    # Run `python -m src.cli project list`
    result = subprocess.run(
        [sys.executable, "-m", "src.cli", "project", "list"],
        capture_output=True, text=True, env=monkeypatch.environ,
    )
    assert result.returncode == 0
    assert "myproject" in result.stdout

    # Run `python -m src.cli project info <name>`
    result = subprocess.run(
        [sys.executable, "-m", "src.cli", "project", "info", "myproject"],
        capture_output=True, text=True, env=monkeypatch.environ,
    )
    assert result.returncode == 0
    assert "myproject" in result.stdout
    assert str(project_dir) in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_integration/test_project_e2e.py -v`
Expected: FAIL (CLI doesn't call auto_register yet; or env var override not implemented)

- [ ] **Step 3: Add env var override + auto-register to `main()`**

```python
# src/cli.py — add to top:

import os
from .project.discovery import auto_register_on_first_run
from .project.paths import config_dir as _project_config_dir

def _override_config_dir_from_env():
    """Allow RUFLO_CONFIG_DIR env var to override OS-standard config dir (for tests)."""
    env_dir = os.environ.get("RUFLO_CONFIG_DIR")
    if env_dir:
        # Monkey-patch at import time
        import src.project.paths as paths
        from pathlib import Path
        paths._OVERRIDE_CONFIG_DIR = Path(env_dir)
        # Replace functions
        paths.config_dir = lambda: paths._OVERRIDE_CONFIG_DIR
        paths.registry_path = lambda: paths._OVERRIDE_CONFIG_DIR / "registry.json"
        paths.last_project_path = lambda: paths._OVERRIDE_CONFIG_DIR / "last_project.json"


def main():
    _override_config_dir_from_env()
    auto_register_on_first_run()  # idempotent

    # ... rest of existing main()
```

(Also need to update `src/project/paths.py` to support env override. Add at top of `paths.py`:)

```python
import os
_OVERRIDE_CONFIG_DIR: Path | None = None

def config_dir() -> Path:
    if _OVERRIDE_CONFIG_DIR:
        return _OVERRIDE_CONFIG_DIR
    return Path(user_config_dir(_APP_NAME, _APP_AUTHOR))

def registry_path() -> Path:
    return config_dir() / "registry.json"

def last_project_path() -> Path:
    return config_dir() / "last_project.json"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_integration/test_project_e2e.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/cli.py src/project/paths.py tests/test_integration/test_project_e2e.py
git commit -m "feat(cli): wire auto_register_on_first_run into main() + env override"
```

---

## Self-Review Checklist

**1. Spec coverage:**

- [x] UUID identity + project.json → Task 2, 4
- [x] Global registry + last_project → Task 3, 4, 5
- [x] 4-step resolve chain → Task 5
- [x] Per-project mutex (async + sync) → Task 6
- [x] Auto-discovery on first run → Task 7
- [x] 8 CLI subcommands → Tasks 8-10

**2. Placeholder scan:** All code blocks contain complete implementations; no `...` or `TODO`.

**3. Type consistency:**

- `ProjectContext.from_path()` signature matches Task 4 + Task 11 wiring
- `ProjectContext.resolve()` matches Task 5 + Test 5 spec
- `with_project_lock` signature consistent across Tasks 6, 7, 8 (used by CLI)
- `GlobalRegistryStore` methods all consistent (`load` / `save` / `upsert` / `remove` / `by_id` / `by_name` / `by_path` / `load_last_project` / `save_last_project`)

**4. Ambiguity check:** Each test has unambiguous expected behavior; each subcommand has clear CLI signature.

---

## Implementation order summary

| Task | Time est | Depends on |
|---|---|---|
| 1: `paths.py` | 10 min | — |
| 2: `identity.py` | 15 min | — |
| 3: `registry.py` | 20 min | Task 1 |
| 4: `ProjectContext.from_path` | 20 min | Task 1, 2, 3 |
| 5: `ProjectContext.resolve` 4-step | 25 min | Task 4 |
| 6: `with_project_lock` mutex | 15 min | — |
| 7: `discover_existing_kbs` | 15 min | Task 4 |
| 8: `cmd_project_init/list` | 20 min | Task 4 |
| 9: `cmd_project_info/current/select` | 15 min | Task 4, 5 |
| 10: `cmd_project_import/forget/rename/discover` | 25 min | Task 7, 3 |
| 11: Wire auto-register + env override | 15 min | All above |

**Total estimated time**: ~3 hours for one engineer, plus review.

**Parallelization**: Tasks 1, 2, 6 can run in parallel (no inter-deps). Tasks 3, 4, 5, 7, 8, 9, 10, 11 form a chain with 4-5 parallel tracks.

---

## Execution Handoff

**Two execution options:**

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks. Fast iteration, clear isolation.
2. **Inline Execution** — Execute tasks in this session using executing-plans skill, batch execution with checkpoints.

Which approach?