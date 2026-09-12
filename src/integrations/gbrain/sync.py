"""Safe, retryable conversion of Wiki manifest diffs into GBrain intents."""
from __future__ import annotations

from dataclasses import dataclass
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Any

from .api import (
    build_wiki_snapshot,
    ensure_search_config,
    reconcile_manifest,
    save_manifest,
    searchable_wiki_files,
    validate_source_ownership,
)
from .types import SearchConfig, WikiSnapshotEntry


@dataclass(frozen=True)
class SyncResult:
    success: bool
    applied: list[str]
    failed: list[str]


def build_import_command(
    project_root: Path, config: SearchConfig, runtime_path: Path, import_root: Path | None = None
) -> list[str]:
    """Build the only allowed initial-import command for this project."""
    del runtime_path  # The caller supplies it as the subprocess cwd.
    return [
        "bun",
        "run",
        "src/cli.ts",
        "import",
        str(import_root or (Path(project_root) / "wiki")),
        "--source-id",
        config.source_id,
    ]


def build_source_add_command(project_root: Path, config: SearchConfig) -> list[str]:
    return [
        "bun",
        "run",
        "src/cli.ts",
        "sources",
        "add",
        config.source_id,
        "--path",
        str(Path(project_root) / "wiki"),
        "--name",
        config.source_name,
        "--no-federated",
    ]


def build_source_status_command() -> list[str]:
    return ["bun", "run", "src/cli.ts", "sources", "status", "--json"]


def _source_is_registered(result: Any, project_root: Path, source_id: str) -> bool:
    payload = json.loads(getattr(result, "stdout", "") or "{}")
    rows = payload.get("sources", []) if isinstance(payload, dict) else []
    row = next((item for item in rows if item.get("source_id") == source_id), None)
    if row is None:
        return False
    local_path = row.get("local_path")
    expected = (Path(project_root) / "wiki").resolve()
    if not local_path or Path(str(local_path)).resolve() != expected:
        raise ValueError("source_ownership_conflict")
    return True


def _prepare_import_root(project_root: Path) -> Path:
    root = Path(project_root)
    staging_parent = root / ".index" / "gbrain"
    staging_parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="gbrain-import-", dir=staging_parent))
    for source in searchable_wiki_files(root):
        relative = source.relative_to(root)
        target = staging / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return staging


def build_mcp_intent(
    operation: str, source_id: str, slug: str, content: str | None
) -> dict[str, Any]:
    if operation == "upsert":
        tool = "put_page"
        arguments = {"slug": slug, "content": content or ""}
    elif operation in {"delete", "restore"}:
        tool = f"{operation}_page"
        arguments = {"slug": slug}
    else:
        raise ValueError(f"unsupported GBrain sync operation: {operation}")
    return {"tool": tool, "source_id": source_id, "arguments": arguments}


def run_initial_import(
    project_root: Path,
    config: SearchConfig,
    runtime_path: Path,
    *,
    runner: Callable[[list[str], Path], Any] | None = None,
) -> list[Any]:
    """Run source registration and import with fixed cwd and argv."""
    command_runner = runner or (
        lambda command, cwd: subprocess.run(
            command, cwd=cwd, capture_output=True, text=True, check=True, shell=False
        )
    )
    staging = _prepare_import_root(Path(project_root))
    try:
        status = command_runner(build_source_status_command(), Path(runtime_path))
        commands = []
        if not _source_is_registered(status, Path(project_root), config.source_id):
            commands.append(command_runner(build_source_add_command(project_root, config), Path(runtime_path)))
        commands.append(
            command_runner(
                build_import_command(project_root, config, runtime_path, staging),
                Path(runtime_path),
            )
        )
        return commands
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def reconcile_and_sync(
    project_root: Path,
    apply_intent: Callable[[str, str, str, str | None], Any],
    *,
    max_attempts: int = 3,
) -> SyncResult:
    """Apply the manifest diff and commit the new manifest only on success.

    ``apply_intent`` is deliberately injected so the worker can use a
    controlled stdio MCP session while tests remain process-free.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    root = Path(project_root)
    config = ensure_search_config(root)
    validate_source_ownership(root, config.source_id)
    snapshot = build_wiki_snapshot(root)
    current = {entry.slug: entry for entry in snapshot}
    plan = reconcile_manifest(root)
    applied: list[str] = []
    failed: list[str] = []

    def apply(operation: str, slug: str) -> bool:
        entry: WikiSnapshotEntry | None = current.get(slug)
        content = None if entry is None else (root / entry.path).read_text(encoding="utf-8")
        for attempt in range(max_attempts):
            try:
                build_mcp_intent(operation, config.source_id, slug, content)
                apply_intent(operation, config.source_id, slug, content)
                return True
            except Exception:
                if attempt == max_attempts - 1:
                    return False
        return False

    for slug in plan.restored:
        if not apply("restore", slug):
            failed.append(slug)
    for slug in [*plan.updated, *plan.added, *plan.restored]:
        if slug in failed:
            continue
        if apply("upsert", slug):
            if slug not in applied:
                applied.append(slug)
        else:
            failed.append(slug)
    for slug in plan.deleted:
        if apply("delete", slug):
            if slug not in applied:
                applied.append(slug)
        else:
            failed.append(slug)
    if failed:
        return SyncResult(False, applied, failed)
    save_manifest(root, snapshot, deleted_slugs=plan.deleted)
    return SyncResult(True, applied, [])


__all__ = [
    "SyncResult",
    "build_import_command",
    "build_mcp_intent",
    "build_source_add_command",
    "build_source_status_command",
    "reconcile_and_sync",
    "run_initial_import",
]
