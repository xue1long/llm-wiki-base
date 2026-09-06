"""Fail-closed validation for series/book release manifests."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .series_model import SCHEMA_VERSION, STATUSES, canonical_digest


def _result(errors: list[str], **extra: Any) -> dict[str, Any]:
    return {"ok": not errors, "errors": errors, **extra}


def validate_book_manifest(payload: object, *, release_id: str | None = None) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return _result(["book-type"])
    for key in ("book_id", "status", "outline_id", "hard_dependencies", "soft_dependencies"):
        if key not in payload:
            errors.append(f"missing:{key}")
    if not isinstance(payload.get("book_id"), str) or not payload.get("book_id"):
        errors.append("book-id")
    if not isinstance(payload.get("required"), bool):
        errors.append("required-type")
    if payload.get("status") not in STATUSES:
        errors.append("status")
    for key in ("hard_dependencies", "soft_dependencies"):
        value = payload.get(key)
        if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
            errors.append(f"{key}-type")
    if release_id is not None and payload.get("release_id") not in (None, release_id):
        errors.append("release-mismatch")
    return _result(errors)


def dependency_report(books: list[dict[str, Any]]) -> dict[str, Any]:
    ids = {b.get("book_id") for b in books if isinstance(b, dict)}
    states = {b.get("book_id"): b.get("status") for b in books if isinstance(b, dict)}
    errors: list[str] = []
    soft_missing: list[str] = []
    for book in books:
        if not isinstance(book, dict):
            continue
        for name, hard in (("hard_dependencies", True), ("soft_dependencies", False)):
            for dep in book.get(name, []) if isinstance(book.get(name), list) else []:
                if not dep or dep not in ids or (hard and states.get(dep) != "ready"):
                    if hard:
                        errors.append(f"hard-dependency:{book.get('book_id')}:{dep}")
                    else:
                        soft_missing.append(str(dep))
    return _result(errors, soft_missing=sorted(set(soft_missing)))


def validate_series_manifest(payload: object) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return _result(["series-type"])
    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema-version")
    for key in ("series_id", "release_id", "status", "books"):
        if key not in payload:
            errors.append(f"missing:{key}")
    if not isinstance(payload.get("series_id"), str) or not payload.get("series_id"):
        errors.append("series-id")
    if not isinstance(payload.get("release_id"), str) or not payload.get("release_id"):
        errors.append("release-id")
    if payload.get("status") not in STATUSES:
        errors.append("status")
    books = payload.get("books")
    if not isinstance(books, list) or not books:
        errors.append("books-type")
        books = []
    seen: set[str] = set()
    for book in books:
        report = validate_book_manifest(book, release_id=payload.get("release_id"))
        errors.extend(f"book:{e}" for e in report["errors"])
        if isinstance(book, dict):
            bid = book.get("book_id")
            if bid in seen:
                errors.append(f"duplicate-book:{bid}")
            seen.add(bid)
    dep = dependency_report(books)
    errors.extend(dep["errors"])
    recorded_digest = payload.get("manifest_sha256")
    if recorded_digest is not None and recorded_digest != canonical_digest(payload):
        errors.append("manifest-hash")
    required = [b for b in books if isinstance(b, dict) and b.get("required") is True]
    ready = all(b.get("status") == "ready" and b.get("release_id", payload.get("release_id")) == payload.get("release_id") for b in required)
    if payload.get("status") == "ready" and (not ready or dep["errors"]):
        errors.append("ready-gate")
    if payload.get("status") == "ready" and any(b.get("status") in {"invalid", "partial"} for b in required):
        errors.append("required-not-ready")
    return _result(errors, soft_missing=dep["soft_missing"], canonical_digest=canonical_digest(payload))


def validate_release_files(manifest: dict[str, Any], root: str | Path) -> dict[str, Any]:
    errors: list[str] = []
    files = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(files, dict):
        return _result(["files-type"])
    base = Path(root)
    for name, expected in files.items():
        path = Path(str(name))
        if path.is_absolute() or ".." in path.parts or path.name != str(name):
            errors.append(f"path:{name}"); continue
        target = base / path
        try:
            actual = hashlib.sha256(target.read_bytes()).hexdigest()
        except OSError:
            errors.append(f"missing:{name}"); continue
        if actual != expected:
            errors.append(f"hash:{name}")
    return _result(errors)


def read_legacy_manifest(payload: object) -> dict[str, Any]:
    """Expose old releases as one anonymous book; never infer new ownership."""
    if not isinstance(payload, dict):
        return {"legacy": True, "series_id": None, "book_id": None, "status": "invalid"}
    return {"legacy": payload.get("schema_version") != SCHEMA_VERSION,
            "series_id": payload.get("series_id") if payload.get("schema_version") == SCHEMA_VERSION else None,
            "book_id": payload.get("book_id") if payload.get("schema_version") == SCHEMA_VERSION else None,
            "status": payload.get("status", "ready"), "manifest": payload}


__all__ = ["validate_book_manifest", "validate_series_manifest", "validate_release_files", "dependency_report", "read_legacy_manifest"]
