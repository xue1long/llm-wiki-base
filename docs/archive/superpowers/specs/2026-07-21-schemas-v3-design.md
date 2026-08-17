# Schemas v3 Design Spec

**Date:** 2026-07-21
**Status:** Approved (pending user sign-off)
**Target codebase:** ruflo-kb (Python 3.11+, master @ 9becebc, post-Wiki-Relations spec)
**Inspired by:** Novel-Knowledge-Base v3.0 schema versioning + forward-compat + up()/down() migration

## Goal

Upgrade ruflo-kb's schema framework from a simple migration script (`src/schemas/migrations/v1_to_v2.py`) to a mature versioned system that supports:

1. **Forward-compatible parsing** — `extra="allow"` for all schemas: unknown fields preserved, not rejected.
2. **Reversible migration classes** — Each version transition is a `Migration` class with `up()` + `down()` + `preview()` + automatic backup.
3. **Schema registry** — Multiple schemas (wiki page, settings, analysis result, judgment) each independently versioned.
4. **Per-project schema_version** — Global `CURRENT_VERSION` + per-project override for legacy support.
5. **Compile-isolated output** — Each migration produces timestamped backup directories + `latest/` symlink.

## Non-goals

- No multi-schema transactional migrations (each schema independent).
- No automatic migration on read (lazy migration deferred).
- No remote schema registry (local only).
- No schema compatibility matrix UI (CLI only).


## Input Contract

> Reference: [`_input_contracts.md`](_input_contracts.md) for cross-spec dependency map.

**This spec provides** (consumed by other specs):

- `Migration` base class (forward-compat + reversible)
- `SchemaRegistry` (multiple schema types)
- `BackupManager` (timestamped backups + latest symlink)
- `ForwardCompatModel` (extra='allow')
- v2.0 → v2.1 migration template

**This spec requires from other specs**:

- **src/shared/**: error classes (MigrationError)

**Phase**: Phase 1 — Foundations (parallel)
**Priority**: P0 — MVP

## Architecture

```
src/schemas/
├── __init__.py             # Public API
├── base.py                 # BaseModel (extra='allow') + SchemaVersion enum
├── registry.py             # SchemaRegistry: version → dataclass mapping
├── migration.py            # Migration base class + MigrationContext
├── migrations/             # One file per migration
│   ├── __init__.py
│   ├── v1_to_v2.py        # Refactored from existing
│   ├── v2_to_v3.py        # NEW: forward-compat parser + relations field
│   └── v3_to_v2.py        # NEW: reverse of v2_to_v3 (down)
├── backup.py               # BackupManager: timestamped dirs + latest symlink
└── errors.py               # MigrationError, IncompatibleSchemaError

CLI:
python -m src.cli schema list                  # List all registered schemas + versions
python -m src.cli schema diff <from> <to>      # Show schema diff
python -m src.cli schema upgrade [--project <id>] [--preview] [--no-backup]
python -m src.cli schema downgrade <to_version> [--project <id>] [--preview]
python -m src.cli schema backup list           # List backups
python -m src.cli schema backup restore <timestamp>
```

## Components

### New modules

```
src/schemas/base.py          (refactored)
src/schemas/registry.py      (extended)
src/schemas/migration.py     (NEW)
src/schemas/backup.py        (NEW)
src/schemas/errors.py        (NEW)
src/schemas/migrations/v2_to_v3.py  (NEW)
src/schemas/migrations/v3_to_v2.py  (NEW)
src/cli_ext/schema_cmd.py    (NEW)
tests/test_schemas/
├── test_base.py
├── test_registry.py
├── test_migration.py
├── test_backup.py
└── test_v2_to_v3.py
```

### Modified modules

| Path | Change |
|---|---|
| `src/schemas/registry.py` | Use `extra="allow"` on all registered models |
| `src/schemas/migrations/v1_to_v2.py` | Refactor as `Migration` class with up()/down()/preview() |
| `src/wiki/page_writer.py` | Frontmatter parse uses forward-compat model |
| `src/project/context.py` | Load `schema_version` per-project; check upgrade availability on init |

## Data structures

```python
# src/schemas/base.py
from pydantic import BaseModel, ConfigDict
from enum import Enum

class SchemaVersion(str, Enum):
    V1_0 = "v1.0"
    V2_0 = "v2.0"
    V2_1 = "v2.1"
    V3_0 = "v3.0"

class ForwardCompatModel(BaseModel):
    """Base model with forward-compatible parsing."""
    model_config = ConfigDict(extra="allow")  # preserve unknown fields

CURRENT_VERSION = SchemaVersion.V2_1   # bumped from V2_0 by Wiki-Relations spec

# Per-schema-type versions (each schema evolves independently)
WIKI_PAGE_VERSION = SchemaVersion.V2_1   # Wiki-Relations added relations field
SETTINGS_VERSION = SchemaVersion.V2_0
ANALYSIS_VERSION = SchemaVersion.V1_0
JUDGMENT_VERSION = SchemaVersion.V1_0
```

```python
# src/schemas/registry.py (extended)
@dataclass
class SchemaEntry:
    name: str                            # "wiki_page" | "settings" | ...
    current_version: SchemaVersion
    model_class: type[ForwardCompatModel]   # Pydantic model
    migrations: dict[tuple[SchemaVersion, SchemaVersion], "Migration"]

class SchemaRegistry:
    @staticmethod
    def register(name: str, version: SchemaVersion, model: type) -> None: ...
    @staticmethod
    def get_model(name: str, version: SchemaVersion) -> type: ...
    @staticmethod
    def current_version(name: str) -> SchemaVersion: ...
    @staticmethod
    def find_migration(name: str, from_ver: SchemaVersion, to_ver: SchemaVersion) -> "Migration": ...
    @staticmethod
    def migration_path(name: str, from_ver: SchemaVersion, to_ver: SchemaVersion) -> list["Migration"]: ...
    @staticmethod
    def list_schemas() -> list[SchemaEntry]: ...
```

```python
# src/schemas/migration.py
@dataclass
class MigrationContext:
    project_id: str
    project_path: Path
    backup_dir: Path | None = None
    dry_run: bool = False

@dataclass
class MigrationPlan:
    from_version: SchemaVersion
    to_version: SchemaVersion
    steps: list[str]                    # human-readable description
    affected_files: list[Path]
    reversible: bool

class Migration(ABC):
    """Base class for reversible schema migrations."""
    
    @property
    @abstractmethod
    def schema_name(self) -> str: ...             # "wiki_page"
    
    @property
    @abstractmethod
    def from_version(self) -> SchemaVersion: ...
    
    @property
    @abstractmethod
    def to_version(self) -> SchemaVersion: ...
    
    @abstractmethod
    def preview(self, ctx: MigrationContext) -> MigrationPlan:
        """Show what will change without modifying files."""
        ...
    
    @abstractmethod
    def up(self, ctx: MigrationContext) -> MigrationResult:
        """Apply migration. Must be idempotent (re-runnable)."""
        ...
    
    @abstractmethod
    def down(self, ctx: MigrationContext) -> MigrationResult:
        """Reverse migration. Must be idempotent."""
        ...

@dataclass
class MigrationResult:
    success: bool
    files_changed: int
    files_added: int = 0
    files_removed: int = 0
    duration_seconds: float = 0.0
    backup_path: Path | None = None
    errors: list[str] = field(default_factory=list)
```

```python
# src/schemas/migrations/v2_to_v3.py
class V2ToV3WikiPageMigration(Migration):
    """v2.0 → v2.1: Wiki-Relations spec adds 'relations' field to WikiPage."""
    
    @property
    def schema_name(self) -> str:
        return "wiki_page"
    
    @property
    def from_version(self) -> SchemaVersion:
        return SchemaVersion.V2_0
    
    @property
    def to_version(self) -> SchemaVersion:
        return SchemaVersion.V2_1
    
    def preview(self, ctx: MigrationContext) -> MigrationPlan:
        wiki_files = list(ctx.project_path.glob("wiki/**/*.md"))
        return MigrationPlan(
            from_version=self.from_version,
            to_version=self.to_version,
            steps=[
                f"Add 'relations: []' field to {len(wiki_files)} wiki pages",
                "Update frontmatter to v2.1 (additive only)",
                "Existing wikilinks in body remain (not auto-migrated to relations)",
            ],
            affected_files=wiki_files,
            reversible=True,
        )
    
    def up(self, ctx: MigrationContext) -> MigrationResult:
        result = MigrationResult(success=True, files_changed=0)
        
        if not ctx.dry_run and not ctx.backup_dir:
            ctx.backup_dir = BackupManager.create_backup(
                ctx.project_path,
                reason=f"v2.0→v2.1 migration ({self.schema_name})",
            )
        
        for md_file in ctx.project_path.glob("wiki/**/*.md"):
            content = md_file.read_text(encoding="utf-8")
            if "schema_version: v2.1" in content:
                continue  # already migrated
            if content.startswith("---\n"):
                # Insert relations: [] after schema_version line
                if "relations:" not in content:
                    content = content.replace(
                        "schema_version: v2.0",
                        "schema_version: v2.1\nrelations: []",
                        1,
                    )
                    if not ctx.dry_run:
                        md_file.write_text(content, encoding="utf-8")
                    result.files_changed += 1
        
        # Update .llm-wiki/project.json schema_version
        project_json = ctx.project_path / ".llm-wiki" / "project.json"
        if project_json.exists() and not ctx.dry_run:
            data = json.loads(project_json.read_text(encoding="utf-8"))
            data["schema_version"] = "v2.1"
            project_json.write_text(json.dumps(data, indent=2), encoding="utf-8")
        
        return result
    
    def down(self, ctx: MigrationContext) -> MigrationResult:
        # Inverse: remove relations field, downgrade schema_version
        result = MigrationResult(success=True, files_changed=0)
        for md_file in ctx.project_path.glob("wiki/**/*.md"):
            content = md_file.read_text(encoding="utf-8")
            if "schema_version: v2.1" in content:
                content = re.sub(r"\n?relations: \[\]\n?", "\n", content)
                content = content.replace("schema_version: v2.1", "schema_version: v2.0")
                if not ctx.dry_run:
                    md_file.write_text(content, encoding="utf-8")
                result.files_changed += 1
        return result
```

```python
# src/schemas/backup.py
class BackupManager:
    BACKUP_ROOT = "<project>/.llm-wiki/.backup"
    
    @staticmethod
    def create_backup(project_path: Path, reason: str) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_dir = project_path / ".llm-wiki" / ".backup" / timestamp
        # Copy files to backup dir
        for src in project_path.glob("wiki/**/*.md"):
            dst = backup_dir / src.relative_to(project_path)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        # Update latest symlink
        latest = project_path / ".llm-wiki" / ".backup" / "latest"
        if latest.exists() or latest.is_symlink():
            latest.unlink()
        latest.symlink_to(backup_dir.name)
        return backup_dir
    
    @staticmethod
    def list_backups(project_path: Path) -> list[BackupInfo]:
        ...
    
    @staticmethod
    def restore(project_path: Path, timestamp: str) -> MigrationResult:
        ...
```

## Forward-compat parsing

```python
# src/schemas/base.py
class ForwardCompatModel(BaseModel):
    model_config = ConfigDict(extra="allow")
    
    def to_yaml_compatible(self) -> dict:
        """Convert to YAML-compatible dict, preserving all fields including unknown."""
        return self.model_dump(exclude_none=False)
    
    @classmethod
    def from_yaml_compatible(cls, data: dict) -> "ForwardCompatModel":
        """Parse forward-compat: unknown fields are kept on instance."""
        return cls.model_validate(data)

# Example: WikiPage v2.1 (extends v2.0 with relations)
class WikiPageV2_1(ForwardCompatModel):
    id: str
    title: str
    type: PageType
    sources: list[str] = field(default_factory=list)
    created_at: int
    updated_at: int
    relations: list[Relation] = field(default_factory=list)   # NEW in v2.1
    # All other v2.0 fields preserved via extra="allow"
```

## CLI surface

```
python -m src.cli schema list
    # List all schemas (wiki_page / settings / analysis_result / judgment)
    # Show CURRENT_VERSION per schema + per-project version

python -m src.cli schema diff <from> <to>
    # Show schema diff (which fields added/removed/changed)
    # Example: schema diff v2.0 v2.1
    # → +relations: list[Relation]

python -m src.cli schema upgrade [--project <id>] [--preview] [--no-backup] [--schema wiki_page|settings|...]
    # Preview: show MigrationPlan
    # Apply: backup → run up() → report

python -m src.cli schema downgrade <target_version> [--project <id>] [--preview]
    # Reverse migration

python -m src.cli schema backup list [--project <id>]
    # List all backups (timestamp + size + reason)

python -m src.cli schema backup restore <timestamp> [--project <id>]
    # Restore files from backup (overwrites current wiki/)
```

## HTTP + MCP

```
GET   /api/v1/projects/{id}/schema                    # current schema versions
GET   /api/v1/projects/{id}/schema/{name}/diff?to=v2.1
POST  /api/v1/projects/{id}/schema/upgrade {preview: bool, schema: "wiki_page"}
POST  /api/v1/projects/{id}/schema/downgrade {to: "v2.0", preview: bool}

MCP tools:
ruflo_kb_schema_list(project_id)
ruflo_kb_schema_diff(project_id, schema_name, from_version, to_version)
ruflo_kb_schema_upgrade(project_id, schema_name, preview)
ruflo_kb_schema_downgrade(project_id, schema_name, to_version, preview)
```

## Error handling

| Stage | Error | Strategy |
|---|---|---|
| Migration load | Migration class not registered | Error: "No migration from {from} to {to} for {schema}" |
| Migration preview | File I/O error | Continue; report files not accessible |
| Migration up | File write error (permission / disk full) | Abort; restore from backup; report error |
| Migration up | Frontmatter parse error | Skip file; log; continue with others |
| Migration up | Backup creation fails | Abort; refuse to migrate without backup |
| Migration down | Backup of v(N+1) state missing | Error + hint "Create backup before downgrading" |
| Migration idempotency | Re-running up() | Detect "already at target version" + skip |
| Per-project schema_version | Doesn't exist in registry | Error + list available versions |
| Forward-compat | Unknown field in YAML | Preserve; log debug "preserved unknown field X" |
| Schema diff | From/to versions same | Return empty diff |
| Restore backup | Backup dir missing | Error + list available backups |
| Restore backup | Current state has unsaved changes | Warning + require `--force` to overwrite |

## Backwards compatibility

- Existing v1.0 → v2.0 migration (`src/schemas/migrations/v1_to_v2.py`) refactored as `Migration` class. Behavior unchanged.
- Existing `src/schemas/registry.py` API (`register_migration`, `get_migration`, `migrate_data`) preserved.
- Per-project `schema_version` field defaults to current version on init.
- Frontmatter parsing with forward-compat is opt-in via `ForwardCompatModel` base; existing parsers unchanged.

## Testing strategy

### Unit tests

| Module | Test focus |
|---|---|
| `src/schemas/base.py` | ForwardCompatModel preserves unknown fields |
| `src/schemas/registry.py` | Migration path computation; multi-hop paths |
| `src/schemas/migration.py` | Migration base class; idempotency |
| `src/schemas/backup.py` | Backup creation; latest symlink; restore |
| `src/schemas/migrations/v2_to_v3.py` | up / down / preview; idempotency |
| `src/cli_ext/schema_cmd.py` | All subcommands; --preview; --no-backup |

### Integration tests

```
tests/test_integration/test_schema_upgrade_e2e.py:
    def test_upgrade_v2_to_v3():
        # Create project at v2.0 with wiki pages
        # Run schema upgrade --preview → show plan
        # Run schema upgrade → apply
        # Verify: frontmatter has schema_version: v2.1, relations: []
        # Verify: backup exists at .llm-wiki/.backup/<ts>/
        # Verify: latest symlink points to backup

    def test_downgrade_v3_to_v2():
        # Upgrade first
        # Run schema downgrade v2.0
        # Verify: schema_version back to v2.0; relations field gone

    def test_forward_compat_unknown_field():
        # Write frontmatter with unknown field "x_custom"
        # Load via ForwardCompatModel
        # Verify: x_custom preserved

    def test_idempotent_upgrade():
        # Upgrade → upgrade again
        # Verify: 2nd call is no-op (files unchanged)
```


## MVP Scope / Polish / Deferred

> This section partitions the spec's features into delivery tiers. See [`_input_contracts.md`](_input_contracts.md) for cross-spec context.

### MVP Scope (P0)

- Migration base class with up()/down()/preview()
- Wiki page schema registry
- Frontmatter loading with extra='allow'
- v2.0 → v2.1 migration (for Wiki Relations spec)
- CLI: `schema {list,diff,upgrade,downgrade,backup}`

### Polish (v2.0.1 or later)

- Multi-schema transactional migrations
- Auto-upgrade on read
- Per-schema version registry

### Deferred (v2.1+)

- Lazy migration on read
- Remote schema registry
- Custom migration hooks

## Implementation order

5 phases:

1. **Foundation** — `ForwardCompatModel` base + `SchemaRegistry` extension + tests
2. **Migration framework** — `Migration` base class + `BackupManager` + refactor `v1_to_v2` + tests
3. **`v2_to_v3` migration** — for Wiki-Relations spec + tests
4. **CLI** — `cmd_schema list/diff/upgrade/downgrade/backup` + tests
5. **Integration** — end-to-end upgrade/downgrade + per-project version detection

## Cost estimation

- Migration runtime: O(N files) per migration. For 1000 wiki pages: ~5 seconds for up/down.
- Backup size: same as wiki/ (~1KB-10KB per page).

## Open questions / deferred

- Lazy migration on read (auto-detect old schema on load + migrate in-memory).
- Multi-schema transactional migrations (atomic across wiki_page + settings).
- Schema diff visualization UI.
- Auto-upgrade on read (warn + offer to upgrade).
- Custom migration hooks (user code runs as part of migration).