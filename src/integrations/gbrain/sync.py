"""Safe, retryable conversion of Wiki manifest diffs into GBrain intents."""
from __future__ import annotations

from dataclasses import dataclass
import subprocess
from pathlib import Path
from typing import Callable, Any

from .api import (
    build_wiki_snapshot,
    ensure_search_config,
    reconcile_manifest,
    save_manifest,
    validate_source_ownership,
)
from .types import SearchConfig, WikiSnapshotEntry


@dataclass(frozen=True)
class SyncResult:
    success: bool
    applied: list[str]
    failed: list[str]


def build_import_command(
    project_root: Path, config: SearchConfig, runtime_path: Path
) -> list[str]:
    """Build the only allowed initial-import command for this project."""
    del runtime_path  # The caller supplies it as the subprocess cwd.
    return [
        "bun",
        "run",
        "src/cli.ts",
        "import",
        str(Path(project_root) / "wiki"),
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
    return [
        command_runner(build_source_add_command(project_root, config), Path(runtime_path)),
        command_runner(build_import_command(project_root, config, runtime_path), Path(runtime_path)),
    ]


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

    for operation, slugs in (
        ("upsert", [*plan.updated, *plan.added]),
        ("delete", plan.deleted),
    ):
        for slug in slugs:
            entry: WikiSnapshotEntry | None = current.get(slug)
            content = None if entry is None else (root / entry.path).read_text(encoding="utf-8")
            for attempt in range(max_attempts):
                try:
                    build_mcp_intent(operation, config.source_id, slug, content)
                    apply_intent(operation, config.source_id, slug, content)
                    applied.append(slug)
                    break
                except Exception:
                    if attempt == max_attempts - 1:
                        failed.append(slug)
    if failed:
        return SyncResult(False, applied, failed)
    save_manifest(root, snapshot)
    return SyncResult(True, applied, [])


__all__ = [
    "SyncResult",
    "build_import_command",
    "build_mcp_intent",
    "build_source_add_command",
    "reconcile_and_sync",
    "run_initial_import",
]
