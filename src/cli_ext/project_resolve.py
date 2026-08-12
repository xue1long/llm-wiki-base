from __future__ import annotations

import sys

from ..lib.project import resolve_ctx_only, resolve_project
from ..project.context import ProjectNotFoundError


def resolve_cli_project(
    project_arg: str | None,
    *,
    with_paths: bool = True,
    by_id_only: bool = True,
):
    try:
        if with_paths:
            return resolve_project(project_arg, by_id_only=by_id_only)
        return resolve_ctx_only(project_arg, by_id_only=by_id_only)
    except ProjectNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
