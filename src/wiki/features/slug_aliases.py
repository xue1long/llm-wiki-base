"""Cross-run slug alias registry.

When the LLM emits a ``[[wikilink]]`` or ``relations[].target``,
it sometimes invents a new variant of an existing slug rather than
copying the canonical one (``qi-dai-gan`` vs ``qi-dai-gan-chuangzuo``,
``urban-xianxia-stream`` vs ``dushi-xianxia-liu``). The resolver
(`wikilink.resolve_wikilink`) is exact-match by filename, so the
variant link resolves to nothing and shows up as broken.

This module is the cross-run glue that closes that gap: an
operator (or a future auto-discovery hook in the generator) can
register that variant X resolves to canonical Y. The resolver then
falls back to the alias chain after exact-match miss.

Persistence: ``<project_root>/.llm-wiki/slug_aliases.json``. We use
``safe_write`` (atomic temp-then-rename) so a crash mid-write never
leaves a torn file.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable, Union

from ...lib.write_hooks import safe_write


_ALIAS_FILE = "slug_aliases.json"
_SCHEMA_VERSION = 1


def _resolve_project_root(project_root: Union[str, Path, os.PathLike]) -> str:
    """Normalize Path-like → str (handles both string and Path inputs)."""
    return str(os.fspath(project_root))


class SlugAliasRegistry:
    """Forward (alias → canonical) and reverse (canonical → [aliases])
    slug maps persisted in ``.llm-wiki/slug_aliases.json`` per project.

    Use ``add()`` / ``add_many()`` to register aliases in memory, then
    ``save()`` to flush to disk. Loading a fresh ``SlugAliasRegistry``
    on the same project root re-reads the JSON.

    Add-only API: this module never deletes entries automatically.
    Operators can edit the file by hand if they need to.
    """

    def __init__(self, project_root: Union[str, Path, os.PathLike]) -> None:
        self._project_root = _resolve_project_root(project_root)
        self._alias_path = (
            Path(self._project_root) / ".llm-wiki" / _ALIAS_FILE
        )
        # In-memory state
        self.aliases: dict[str, str] = {}
        self.aliases_rev: dict[str, list[str]] = {}
        self._load()

    # ── Persistence ──────────────────────────────────────────────
    def _load(self) -> None:
        if not self._alias_path.exists():
            return
        try:
            raw = json.loads(self._alias_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        self.aliases = dict(raw.get("aliases") or {})
        # Rebuild reverse index defensively (don't trust disk for it).
        self.aliases_rev = {}
        for alias, canonical in self.aliases.items():
            self.aliases_rev.setdefault(canonical, []).append(alias)

    def save(self) -> None:
        """Write the registry to ``.llm-wiki/slug_aliases.json`` atomically."""
        payload = {
            "version": _SCHEMA_VERSION,
            "aliases": self.aliases,
            "aliases_rev": self.aliases_rev,
            "last_modified": _now_iso(),
        }
        content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        self._alias_path.parent.mkdir(parents=True, exist_ok=True)
        safe_write(str(self._alias_path), content)

    # ── Mutations ────────────────────────────────────────────────
    def add(self, alias: str, canonical: str) -> None:
        """Register ``alias`` → ``canonical``. If ``alias`` was already
        registered (possibly pointing to a different canonical), its
        reverse entry is updated accordingly so the reverse index
        never lies.
        """
        if not alias or not canonical:
            return
        previous_canonical = self.aliases.get(alias)
        # If alias was previously pointing elsewhere, drop it from old
        # canonical's reverse index.
        if previous_canonical and previous_canonical != canonical:
            old_list = self.aliases_rev.get(previous_canonical, [])
            if alias in old_list:
                old_list.remove(alias)
            if not old_list:
                self.aliases_rev.pop(previous_canonical, None)
        # Forward
        self.aliases[alias] = canonical
        # Reverse (idempotent: skip if already present)
        rev = self.aliases_rev.setdefault(canonical, [])
        if alias not in rev:
            rev.append(alias)

    def add_many(self, pairs: Iterable[tuple[str, str]]) -> None:
        for alias, canonical in pairs:
            self.add(alias, canonical)

    # ── Queries ──────────────────────────────────────────────────
    def get_canonical(self, alias: str) -> str | None:
        """Forward lookup. Returns the canonical slug for ``alias``,
        or None if no alias is registered. The return value is the
        canonical page id; the caller is responsible for checking
        whether that page actually exists on disk.
        """
        return self.aliases.get(alias)

    def has_aliases_for(self, canonical: str) -> list[str]:
        """Reverse lookup. Returns the list of aliases that point to
        ``canonical``, or [] if none. Order preserved (insertion order).
        """
        return list(self.aliases_rev.get(canonical, []))


# ── helper ────────────────────────────────────────────────────
def _now_iso() -> str:
    """ISO-8601 UTC timestamp with no microseconds. Format the
    registry's ``last_modified`` field uses.
    """
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
