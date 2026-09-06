"""Versioned book-series manifest contract."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = "series-manifest-v1"
STATUSES = frozenset({"draft", "partial", "ready", "invalid"})
_TRANSITIONS = {"draft": frozenset({"partial", "invalid"}),
                "partial": frozenset({"ready", "invalid"}),
                "ready": frozenset(), "invalid": frozenset()}


def _list(value: Any) -> list[str]:
    return list(value) if isinstance(value, list) else []


@dataclass(frozen=True)
class BookManifest:
    book_id: str
    required: bool
    status: str
    outline_id: str | None = None
    hard_dependencies: list[str] = field(default_factory=list)
    soft_dependencies: list[str] = field(default_factory=list)
    release_id: str | None = None
    hashes: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = {"book_id": self.book_id, "required": self.required, "status": self.status,
                "outline_id": self.outline_id, "hard_dependencies": list(self.hard_dependencies),
                "soft_dependencies": list(self.soft_dependencies)}
        if self.release_id is not None:
            data["release_id"] = self.release_id
        if self.hashes:
            data["hashes"] = dict(self.hashes)
        return data

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BookManifest":
        return cls(str(payload.get("book_id", "")), payload.get("required") is True,
                   str(payload.get("status", "")), payload.get("outline_id"),
                   _list(payload.get("hard_dependencies")), _list(payload.get("soft_dependencies")),
                   payload.get("release_id"), payload.get("hashes") if isinstance(payload.get("hashes"), dict) else {})


@dataclass(frozen=True)
class SeriesManifest:
    series_id: str
    release_id: str
    status: str
    books: list[BookManifest] = field(default_factory=list)
    manifest_sha256: str | None = None
    schema_version: str = SCHEMA_VERSION

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        data = {"schema_version": self.schema_version, "series_id": self.series_id,
                "release_id": self.release_id, "status": self.status,
                "books": [book.to_dict() for book in self.books]}
        if include_digest and self.manifest_sha256:
            data["manifest_sha256"] = self.manifest_sha256
        return data

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SeriesManifest":
        books = payload.get("books") if isinstance(payload.get("books"), list) else []
        return cls(str(payload.get("series_id", "")), str(payload.get("release_id", "")),
                   str(payload.get("status", "")), [BookManifest.from_dict(x) for x in books if isinstance(x, dict)],
                   payload.get("manifest_sha256"), str(payload.get("schema_version", "")))


def canonical_digest(payload: dict[str, Any]) -> str:
    """Digest canonical JSON; the manifest's own digest field is excluded."""
    clean = dict(payload)
    for key in ("manifest_sha256", "canonical_digest"):
        clean.pop(key, None)
    encoded = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def transition_status(current: str, target: str) -> str:
    if current not in STATUSES or target not in STATUSES or target not in _TRANSITIONS[current]:
        raise ValueError(f"illegal manifest status transition: {current!r} -> {target!r}")
    return target


__all__ = ["SCHEMA_VERSION", "STATUSES", "BookManifest", "SeriesManifest", "canonical_digest", "transition_status"]
