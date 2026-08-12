"""SchemaRegistry — parse project schema.md for custom page types.

schema.md (written by `project init` or a project template) declares page
types and their directories in a Markdown table:

    | type     | directory      |
    |----------|----------------|
    | source   | wiki/sources   |
    | thesis   | wiki/thesis    |   <- custom: not in the PageType enum

Built-in types (source/entity/concept/synthesis/claim/decision/procedure/event)
are skipped — they already have a home in `_TYPE_TO_DIR`. Every other row
is a custom type: LLM may emit it, Generator must accept it, and it routes
to its own `wiki/<directory>/` instead of the base type's dir.

Custom types fall back to a base PageType (default CONCEPT) for template
rendering. The row may carry a third column to override the base type:

    | type   | directory   | extends |
    |--------|-------------|---------|
    | thesis | wiki/thesis | concept |
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .core.types import PageType

_logger = logging.getLogger(__name__)

# A `| a | b |` table row. Captures the first two cells (type, directory)
# and any optional third (extends). Ignore the header separator row.
_ROW_RE = re.compile(r"^\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|(?:\s*([^|]+?)\s*\|)?\s*$")
_SEP_RE = re.compile(r"^\s*\|[\s:-]+\|[\s:-]+\|")
_TYPE_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]*$")


@dataclass(frozen=True)
class CustomTypeDef:
    name: str                # "thesis"
    directory: str           # "thesis" (relative under wiki/)
    extends: PageType        # PageType.CONCEPT


def _parse_schema_text(schema_text: str) -> dict[str, CustomTypeDef]:
    """Parse *schema_text*, returning ``{name: CustomTypeDef}`` for custom types."""
    known = {t.value for t in PageType}
    out: dict[str, CustomTypeDef] = {}
    for line in schema_text.splitlines():
        if _SEP_RE.match(line):
            continue
        m = _ROW_RE.match(line)
        if not m:
            continue
        name = m.group(1).strip()
        # Skip the header row (column name "type" is not a real type).
        if name == "type" or not name:
            continue
        directory = m.group(2).strip().replace("\\", "/")
        extends_raw = (m.group(3) or "concept").strip()
        if name in known:
            continue
        # directory may be "wiki/thesis" or "thesis" — keep the terminal segment.
        if not _TYPE_NAME_RE.fullmatch(name):
            _logger.warning("[SchemaRegistry] ignoring invalid type name %r", name)
            continue
        if directory.startswith("/") or re.match(r"^[A-Za-z]:/", directory):
            _logger.warning("[SchemaRegistry] ignoring absolute directory %r", directory)
            continue
        if directory.startswith("wiki/"):
            directory = directory[5:]
        directory = directory.strip("/")
        parts = PurePosixPath(directory).parts
        if not parts or any(part in ("", ".", "..") for part in parts):
            _logger.warning("[SchemaRegistry] ignoring unsafe directory %r", directory)
            continue
        try:
            extends = PageType(extends_raw)
        except ValueError:
            extends = PageType.CONCEPT
        out[name] = CustomTypeDef(name=name, directory="/".join(parts), extends=extends)
    return out


class SchemaRegistry:
    """Runtime access to a project's custom page types from its schema.md."""

    def __init__(
        self, custom: dict[str, CustomTypeDef] | None = None, schema_text: str = "",
    ) -> None:
        self._custom = custom or {}
        self.schema_text = schema_text

    @classmethod
    def from_project(cls, root: Path | str) -> "SchemaRegistry":
        schema_path = Path(root) / "schema.md"
        try:
            return cls.from_schema_text(schema_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls.empty()
        except OSError as exc:
            _logger.warning("[SchemaRegistry] cannot read %s: %s", schema_path, exc)
            return cls.empty()

    @classmethod
    def from_schema_text(cls, schema_text: str) -> "SchemaRegistry":
        return cls(_parse_schema_text(schema_text), schema_text=schema_text)

    @classmethod
    def empty(cls) -> "SchemaRegistry":
        return cls()

    def get_def(self, type_name: str) -> CustomTypeDef | None:
        return self._custom.get(type_name)

    def get_directory(self, type_name: str) -> str | None:
        d = self._custom.get(type_name)
        return d.directory if d else None

    def get_base_type(self, type_name: str) -> PageType:
        """Return the base PageType for *type_name* (CONCEPT fallback)."""
        d = self._custom.get(type_name)
        return d.extends if d else PageType.CONCEPT

    def is_custom(self, type_name: str) -> bool:
        return type_name in self._custom

    def all_custom_type_names(self) -> list[str]:
        return sorted(self._custom)

    def all_type_names(self) -> list[str]:
        """Built-in page types + custom types (for the Analyzer's type union)."""
        return sorted(t.value for t in PageType) + [
            n for n in self.all_custom_type_names() if n not in {t.value for t in PageType}
        ]
