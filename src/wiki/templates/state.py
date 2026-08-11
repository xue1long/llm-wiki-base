"""Bundled-template version tracking for Plan 25 v3.

Persists a small JSON record at
``~/.config/ruflo-kb/wiki-templates/.bundled-state.json`` so we can:

  1. Detect when bundled templates have been upgraded between runs
     (compare sha256 of shipped files against the captured sha256).
  2. Let the CLI show current vs bundled status via
     `wiki-templates status`.
  3. Support `wiki-templates diff` (compare user override vs bundled).

Cross-version migration (v1 → v2) is explicitly OUT OF SCOPE — see
docs/superpowers/plans/2026-07-25-wiki-page-templates.md REV 2.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


_log = logging.getLogger(__name__)


STATE_PATH = Path.home() / ".config" / "ruflo-kb" / "wiki-templates" / ".bundled-state.json"


@dataclass
class BundledEntry:
    version: str
    sha256: str
    captured_at: str  # ISO 8601


@dataclass
class State:
    """Persisted JSON state. Schema version 1."""

    schema_version: int = 1
    bundled: dict[str, BundledEntry] = field(default_factory=dict)  # type -> entry

    @classmethod
    def load(cls, path: Path = STATE_PATH) -> "State":
        if not path.is_file():
            return cls()
        try:
            raw_text = path.read_text(encoding="utf-8")
            raw = json.loads(raw_text)
        except json.JSONDecodeError as e:
            # O-5: corrupt JSON — back the file up for post-mortem, log
            # a warning naming the path + reason, and return a fresh
            # state so the next status call rebuilds from current
            # bundled. Without the backup, users lose all upgrade
            # history with no diagnostic trail.
            backup = path.with_suffix(path.suffix + ".corrupt")
            try:
                backup.write_text(raw_text, encoding="utf-8")
            except OSError as backup_err:
                _log.warning(
                    "wiki-templates state file at %s is corrupt (%s); "
                    "also failed to back up to %s: %s",
                    path, e, backup, backup_err,
                )
                return cls()
            _log.warning(
                "wiki-templates state file at %s is corrupt (%s); "
                "backed up to %s and starting fresh. The next "
                "`wiki-templates status` will rebuild from current bundled.",
                path, e, backup,
            )
            return cls()
        except OSError as e:
            # Unreadable file (permission denied, path is a directory,
            # etc). No backup possible since we couldn't read it.
            # Don't crash — return fresh state and let next write fix it.
            _log.warning(
                "wiki-templates state file at %s is unreadable (%s); "
                "starting fresh. Next save() will rewrite it.",
                path, e,
            )
            return cls()
        return cls(
            schema_version=raw.get("schema_version", 1),
            bundled={
                k: BundledEntry(**v) for k, v in raw.get("bundled", {}).items()
            },
        )

    def save(self, path: Path = STATE_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "schema_version": self.schema_version,
            "bundled": {k: asdict(v) for k, v in self.bundled.items()},
        }
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def diff(self, current_bundled: dict[str, BundledEntry]) -> list[str]:
        """Return list of page types whose bundled sha256 has changed."""
        changed: list[str] = []
        for page_type, cur in current_bundled.items():
            prev = self.bundled.get(page_type)
            if prev is None or prev.sha256 != cur.sha256:
                changed.append(page_type)
        return changed


def compute_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capture_current_bundled(bundled_dir: Path) -> dict[str, BundledEntry]:
    """Read all bundled templates and return their version + sha256.

    Skips files without a `wiki-template-version` header (they would
    fail the resolver anyway). Used to populate / refresh the state
    file.

    Malformed bundled files (e.g. type header wrong, missing version
    header) are logged as ERROR rather than silently skipped — the
    operator needs to know that a shipped template is broken before
    the next `wiki-templates status` call otherwise shows a missing
    PageType with no diagnostic trail. The malformed file is excluded
    from the returned dict so `status` can still report the rest of
    the bundled templates correctly.
    """
    from .parser import parse, TemplateParseError
    from .types import PageType

    out: dict[str, BundledEntry] = {}
    for f in bundled_dir.glob("*.md"):
        slug = f.stem
        # Only include known PageTypes (skips _base.md fragments etc.)
        if not any(slug == pt.value for pt in PageType):
            continue
        raw = f.read_text(encoding="utf-8")
        try:
            ast = parse(raw, expected_type=PageType(slug))
        except TemplateParseError as e:
            # F-5: bundled file shipped in this repo is malformed — log
            # loudly so the operator notices on the next status call.
            # Without this, a broken bundled file would silently vanish
            # and look like "type missing from bundled" — which is the
            # wrong diagnostic.
            _log.error(
                "bundled template %s failed to parse: %s. "
                "It will be excluded from `wiki-templates status` "
                "until fixed. Re-install the bundled templates or "
                "patch the file to restore the wiki-template-version "
                "and wiki-template-type headers.",
                f, e,
            )
            continue
        out[slug] = BundledEntry(
            version=ast.version or "0.0.0",
            sha256=compute_sha256(f),
            captured_at=_now_iso(),
        )
    return out


def _now_iso() -> str:
    """ISO 8601 UTC timestamp without external deps."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def refresh_state(state_path: Path = STATE_PATH) -> tuple[State, list[str]]:
    """Re-read bundled dir and update state file. Returns (new_state, changed_types).

    Use this at server startup or from `wiki-templates status` to keep
    the recorded sha256 current.
    """
    from .types import BUNDLED_DIR

    state = State.load(state_path)
    current = capture_current_bundled(BUNDLED_DIR)
    changed = state.diff(current)
    state.bundled = current
    state.save(state_path)
    return state, changed
