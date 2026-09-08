"""Instance-owned Book editing rules."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path


_RULES_FILENAME = "book.rules.md"


@dataclass(frozen=True, slots=True)
class BookRulesSnapshot:
    """The immutable rules input captured for one Book build."""

    text: str
    rules_hash: str


class BookRulesError(RuntimeError):
    """Raised when instance-owned Book rules cannot be loaded safely."""


def _canonicalize_rules(text: str) -> str:
    if text.startswith("\ufeff"):
        text = text[1:]
    return text.replace("\r\n", "\n").replace("\r", "\n")


def load_book_rules(project_root: Path | str) -> BookRulesSnapshot:
    """Read and freeze ``<project_root>/book.rules.md`` once."""
    path = Path(project_root) / _RULES_FILENAME
    try:
        text = _canonicalize_rules(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise BookRulesError(f"unable to read Book rules: {path}") from exc

    if not text.strip():
        raise BookRulesError(f"Book rules are empty: {path}")

    return BookRulesSnapshot(
        text=text,
        rules_hash=sha256(text.encode("utf-8")).hexdigest(),
    )
