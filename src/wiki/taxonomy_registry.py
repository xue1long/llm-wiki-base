"""Project-local taxonomy.md parser and validation boundary."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

_LOGGER = logging.getLogger(__name__)
_MAX_BYTES = 64 * 1024
_TITLE = re.compile(r"^#\s+Taxonomy\s*$", re.IGNORECASE)
_CATEGORY = re.compile(r"^##\s+(.+?)\s*$")
_ITEM = re.compile(r"^-\s+(.+?)\s*$")
_ALIASES = re.compile(r"^(.*?)（aliases:\s*(.*?)）\s*$", re.IGNORECASE)
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


@dataclass(frozen=True)
class TaxonomyRegistry:
    """Read-only project taxonomy used as LLM context and a soft/strict gate."""

    categories: dict[str, list[str]] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    source_text: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.categories

    @property
    def injection_text(self) -> str:
        if self.is_empty:
            return "(未配置)"
        lines = ["# Taxonomy", "", "仅使用以下项目分类；不要创建未列出的分类："]
        for category, children in self.categories.items():
            lines.append(f"## {category}")
            lines.extend(f"- {child}" for child in children)
        return "\n".join(lines)

    def validate(self, category: str, taxonomy_sub: str) -> list[str]:
        """Return validation errors; an empty registry preserves old behavior."""
        if self.is_empty:
            return []
        errors: list[str] = []
        if category not in self.categories:
            errors.append(f"unknown category: {category}")
            return errors
        if taxonomy_sub and taxonomy_sub not in self.categories[category]:
            errors.append(f"unknown taxonomy_sub: {taxonomy_sub}")
        return errors

    @classmethod
    def from_project(cls, root: Path | str, *, strict: bool = False) -> "TaxonomyRegistry":
        path = Path(root) / "taxonomy.md"
        try:
            if not path.exists():
                return cls()
            if path.stat().st_size > _MAX_BYTES:
                raise ValueError(f"taxonomy.md exceeds {_MAX_BYTES} bytes")
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError, ValueError) as exc:
            if strict:
                raise ValueError(f"Invalid taxonomy.md: {exc}") from exc
            _LOGGER.warning("[TaxonomyRegistry] cannot read %s: %s", path, exc)
            return cls(errors=[str(exc)])
        try:
            return cls.from_text(text)
        except ValueError as exc:
            if strict:
                raise
            _LOGGER.warning("[TaxonomyRegistry] ignoring %s: %s", path, exc)
            return cls(errors=[str(exc)], source_text=text)

    @classmethod
    def from_text(cls, text: str) -> "TaxonomyRegistry":
        if not text.strip():
            return cls()
        lines = _HTML_COMMENT.sub("", text).splitlines()
        if not any(_TITLE.match(line.strip()) for line in lines):
            raise ValueError("taxonomy.md must start with '# Taxonomy'")

        categories: dict[str, list[str]] = {}
        aliases: dict[str, str] = {}
        current: str | None = None
        for raw in lines:
            line = raw.strip()
            if not line or _TITLE.match(line):
                continue
            category_match = _CATEGORY.match(line)
            if category_match:
                current = category_match.group(1).strip()
                if not current or current in categories:
                    raise ValueError(f"duplicate or empty category: {current!r}")
                categories[current] = []
                continue
            item_match = _ITEM.match(line)
            if item_match:
                if current is None:
                    raise ValueError("taxonomy item appears before a category")
                value = item_match.group(1).strip()
                alias_match = _ALIASES.match(value)
                if alias_match:
                    value = alias_match.group(1).strip()
                    names = [a.strip() for a in alias_match.group(2).split(",") if a.strip()]
                else:
                    names = []
                if not value or value in categories[current]:
                    raise ValueError(f"duplicate or empty taxonomy value: {value!r}")
                categories[current].append(value)
                for alias in names:
                    if alias in aliases or alias in categories or alias == value:
                        raise ValueError(f"duplicate taxonomy alias: {alias!r}")
                    aliases[alias] = value
                continue
            if line.startswith("#"):
                continue
            if line:
                raise ValueError(f"unsupported taxonomy syntax: {line}")

        if not categories or any(not values for values in categories.values()):
            raise ValueError("taxonomy must define categories with values")
        return cls(categories=categories, aliases=aliases, source_text=text)
