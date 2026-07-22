"""Centralised project-resolution helpers — single source of truth for CLI + routes.

Replaces 9 hand-rolled `_resolve_ctx` copies that previously lived in
src/cli_ext/* and src/server/routes/* (each duplicating the same
try/except + WikiPaths construction logic).

Note: ProjectContext exposes `ctx.path` (Path), NOT `ctx.paths`. WikiPaths
is derived from the path. See ADR-0004.
"""
from __future__ import annotations

from ..project.context import ProjectContext
from ..wiki.paths import WikiPaths


def resolve_project(
    project_arg: str | None,
    by_id_only: bool = True,
) -> tuple[ProjectContext, WikiPaths]:
    """Resolve a project by arg / CWD / last-pointer; return (ctx, paths).

    On failure, propagates `ProjectNotFoundError` from the underlying
    ProjectContext.resolve. Callers decide how to handle the error:
      - CLI: print to stderr + sys.exit(2)
      - HTTP route: raise HTTPException(404, str(e))

    Returns:
        (ctx, paths) — always together so callers can't forget to
        derive WikiPaths (the source of the ADR-0004 footgun).
    """
    ctx = ProjectContext.resolve(project_arg, by_id_only=by_id_only)
    return ctx, WikiPaths(ctx.path)


def resolve_ctx_only(
    project_id: str | None,
    by_id_only: bool = True,
) -> ProjectContext:
    """Resolve and return only the ProjectContext (no WikiPaths).

    Use this when the caller doesn't need filesystem paths (e.g. a
    route that only needs project metadata). For most cases prefer
    `resolve_project` which returns both halves together.
    """
    return ProjectContext.resolve(project_id, by_id_only=by_id_only)
