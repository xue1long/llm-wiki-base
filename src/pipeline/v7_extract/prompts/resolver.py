"""Prompt resolver — three-layer override + path whitelist.

D1 (layer override):
    project > user > bundled. Mirrors ``src/wiki/templates/resolver.py``.

D6 (hot reload):
    Every call to ``resolve()`` re-reads the file from disk. No caching.
    Author edits ``knowledge/novel-wiki/.v7-prompts/classify.toml`` and
    the next pipeline run picks it up immediately. ~10ms per call.

D9 (path whitelist):
    The resolver ONLY accepts prompts from a fixed set of allowed
    roots. Any attempt to resolve from a non-whitelisted path raises
    ``PromptPathNotAllowedError``. This prevents a malicious
    ``/tmp/evil.toml`` from sneaking in via symlink tricks or
    misconfigured environment variables.
"""
from __future__ import annotations

import os
from pathlib import Path

from .ast import PromptAST, PromptSource, PromptTemplate
from .parser import PromptParseError, parse_prompt


# The three allowed roots (project > user > bundled).
# ``bundled`` is computed relative to this file (not user-overridable).
BUNDLED_ROOT: Path = Path(__file__).parent / "builtin"

# Project-level override — relative to the project root passed to
# ``resolve()``. The user can configure this via V7_PROMPTS_PROJECT_ROOT.
_DEFAULT_PROJECT_PROMPTS_DIRNAME: str = ".v7-prompts"


def _user_root() -> Path:
    """User-level override: ``~/.config/ruflo-kb/v7-prompts``.

    Same convention as ``src/wiki/templates/resolver.py``.
    """
    return Path.home() / ".config" / "ruflo-kb" / "v7-prompts"


class PromptNotFoundError(Exception):
    """No prompt TOML found in any of the three allowed roots."""


class PromptPathNotAllowedError(Exception):
    """D9: ``resolve()`` was asked to consider a path outside the whitelist."""


def resolve(
    prompt_kind: str,
    project_root: Path | str | None = None,
) -> PromptTemplate:
    """Resolve a prompt by name from the three-layer override.

    Args:
        prompt_kind: e.g. "classify", "completeness", "cluster", "fill_slots"
        project_root: the v7_extract project's root (e.g.
            ``Path("knowledge/novel-wiki")``). ``project_root/.v7-prompts``
            is checked first.

    Returns:
        ``PromptTemplate`` ready to feed into ``render_prompt``.

    Raises:
        PromptPathNotAllowedError: D9 — if project_root resolves to a
            path outside the whitelist (see ``_is_allowed_root``).
        PromptParseError: if the TOML is malformed or fails schema
            validation (D9 enum check).
        PromptNotFoundError: if no allowed root contains the prompt.
    """
    search_roots: list[tuple[Path, PromptSource]] = []

    if project_root is not None:
        pr = Path(project_root)
        if not _is_allowed_root(pr):
            raise PromptPathNotAllowedError(
                f"D9: project_root {pr} is not in the whitelist. "
                f"Allowed roots: project must end with "
                f"'{_DEFAULT_PROJECT_PROMPTS_DIRNAME}' parent."
            )
        search_roots.append((pr / _DEFAULT_PROJECT_PROMPTS_DIRNAME, "project"))

    search_roots.append((_user_root(), "user"))
    search_roots.append((BUNDLED_ROOT, "bundled"))

    for root, source in search_roots:
        candidate = root / f"{prompt_kind}.toml"
        if candidate.is_file():
            ast = parse_prompt(candidate)
            return _to_template(ast, source=source, path=candidate)

    raise PromptNotFoundError(
        f"No prompt TOML found for kind={prompt_kind!r}. "
        f"Searched: {[str(r) for r, _ in search_roots]}"
    )


def _is_allowed_root(project_root: Path) -> bool:
    """D9: project_root must be inside the workspace.

    Heuristic: project_root must not live under any of:
      - /tmp (POSIX / Git-Bash ``/tmp``)
      - $TMPDIR (POSIX temp dir env)
      - $TEMP (Windows temp dir env)
      - $TMP (Windows alt temp dir env)

    On Windows, ``/tmp`` is mapped to a non-temp path by Git-Bash, so
    we only forbid it if it actually resolves inside a real temp dir.

    We intentionally keep this permissive otherwise — v7_extract is
    used in many contexts (CI, local dev, mounted workspaces).
    """
    try:
        resolved = project_root.resolve(strict=False)
    except OSError:
        return False

    forbidden_prefixes: list[Path] = []
    # POSIX / Git-Bash /tmp — only forbid if it actually resolves to a
    # temp-like location (Git-Bash maps /tmp to the user's home on some
    # setups, which we don't want to forbid).
    try:
        if Path("/tmp").resolve().as_posix() == Path(resolved.anchor + "tmp").as_posix():
            forbidden_prefixes.append(Path("/tmp").resolve())
    except OSError:
        pass
    # Windows-style envs
    for env_name in ("TMPDIR", "TEMP", "TMP"):
        env_val = os.environ.get(env_name)
        if env_val:
            try:
                forbidden_prefixes.append(Path(env_val).resolve())
            except OSError:
                pass

    resolved_posix = resolved.as_posix().rstrip("/")
    for prefix in forbidden_prefixes:
        prefix_posix = prefix.as_posix().rstrip("/")
        if prefix_posix and resolved_posix.startswith(prefix_posix + "/"):
            return False
    return True


def _to_template(ast: PromptAST, source: PromptSource, path: Path) -> PromptTemplate:
    return PromptTemplate(
        prompt_kind=ast.prompt_kind,
        version=ast.version,
        system_section=ast.system_section,
        user_template=ast.user_section,
        output_schema=ast.output_schema,
        source=source,
        path=path,
    )
