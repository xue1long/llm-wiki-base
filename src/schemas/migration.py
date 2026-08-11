# src/schemas/migration.py
"""Migration framework — reversible schema upgrades with backup."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class MigrationSafetyError(Exception):
    """Raised when a migration runs without required backup."""


class MigrationNotFoundError(Exception):
    """Raised when a requested migration is not registered."""


class SchemaVersion(str, Enum):
    V1_0 = "v1.0"
    V2_0 = "v2.0"
    V2_1 = "v2.1"
    V2_2 = "v2.2"
    V3_0 = "v3.0"


@dataclass
class MigrationContext:
    """Context passed to Migration.up() / .down() / .preview()."""
    project_id: str
    project_path: Path
    backup_dir: Path | None = None          # REQUIRED for up()/down() (enforced)
    dry_run: bool = False                   # preview-only if True


@dataclass
class MigrationPlan:
    from_version: SchemaVersion
    to_version: SchemaVersion
    steps: list[str] = field(default_factory=list)
    affected_files: list[Path] = field(default_factory=list)
    reversible: bool = True


@dataclass
class MigrationResult:
    success: bool
    files_changed: int = 0
    files_added: int = 0
    files_removed: int = 0
    backup_path: Path | None = None
    errors: list[str] = field(default_factory=list)


class Migration(ABC):
    """Base class for reversible schema migrations.

    Subclasses declare schema_name + from_version + to_version + implement
    up() / down() / preview(). up() and down() MUST be idempotent.
    """

    @property
    @abstractmethod
    def schema_name(self) -> str: ...

    @property
    @abstractmethod
    def from_version(self) -> SchemaVersion: ...

    @property
    @abstractmethod
    def to_version(self) -> SchemaVersion: ...

    @abstractmethod
    def preview(self, ctx: MigrationContext) -> MigrationPlan: ...

    @abstractmethod
    def up(self, ctx: MigrationContext) -> MigrationResult: ...

    @abstractmethod
    def down(self, ctx: MigrationContext) -> MigrationResult: ...

    def _require_backup(self, ctx: MigrationContext) -> None:
        """Safety check: up()/down() require backup_dir unless dry_run."""
        if ctx.dry_run:
            return
        if ctx.backup_dir is None:
            raise MigrationSafetyError(
                f"Migration {self.from_version}→{self.to_version} requires backup_dir. "
                f"Call BackupManager.create_backup() first."
            )


def _migrate_via_registry(data: dict[str, Any], target: SchemaVersion) -> dict[str, Any]:
    """Migrate dict-based data via the registry (legacy API helper).

    Walks the migration path from data's current schema_version to target,
    applying each migration's up() in sequence. Migrations registered for
    the file-based path don't accept dicts, so this is a no-op for now.
    """
    # The current migration classes operate on file paths, not dicts.
    # This shim exists so legacy callers can import it without crashing.
    return data
