"""Persistent Book editorial input for the rule-only compiler stage."""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .model import WikiSnapshot
from .tutorial_path import validate_tutorial_paths

BOOK_SCHEMA_VERSION = "book-v1"
CURATION_SCHEMA_VERSION = "book-curation-v1"
OUTLINE_SCHEMA_VERSION = "book-outline-v1"
PATH_SCHEMA_VERSION = "tutorial-path-v1"

DISPOSITIONS = frozenset({"include", "duplicate", "conflict", "exclude", "unresolved"})
FRESHNESS_STATES = frozenset({"fresh", "stale", "building", "failed"})
BODY_POLICY = "generated_only"


@dataclass(frozen=True)
class BookEditorialState:
    """The four durable JSON inputs used by Book compilation."""

    book: dict[str, Any]
    curation: dict[str, Any]
    outline: dict[str, Any]
    paths: dict[str, Any]

    def with_book_freshness(self, value: str) -> "BookEditorialState":
        book = copy.deepcopy(self.book)
        book["book_freshness"] = value
        return replace(self, book=book)

    def with_curation_pages(self, pages: tuple[dict[str, Any], ...]) -> "BookEditorialState":
        curation = copy.deepcopy(self.curation)
        curation["pages"] = [copy.deepcopy(page) for page in pages]
        return replace(self, curation=curation)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def editorial_state_hash(state: BookEditorialState) -> str:
    payload = {"book": state.book, "curation": state.curation,
               "outline": state.outline, "paths": state.paths}
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _chapter_ids(outline: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for volume in outline.get("volumes", ()) if isinstance(outline.get("volumes"), list) else ():
        if not isinstance(volume, dict):
            continue
        chapters = volume.get("chapters", ())
        for chapter in chapters if isinstance(chapters, list) else ():
            if isinstance(chapter, dict) and isinstance(chapter.get("chapter_id"), str):
                result.add(chapter["chapter_id"])
    return result


def _all_chapter_ids(outline: dict[str, Any]) -> list[str]:
    return [
        chapter["chapter_id"]
        for volume in outline.get("volumes", ())
        if isinstance(volume, dict)
        for chapter in volume.get("chapters", ())
        if isinstance(volume.get("chapters"), list)
        if isinstance(chapter, dict)
        if isinstance(chapter.get("chapter_id"), str)
    ]


def _outline_page_owners(outline: dict[str, Any]) -> dict[str, list[str]]:
    owners: dict[str, list[str]] = {}
    for volume in outline.get("volumes", ()) if isinstance(outline.get("volumes"), list) else ():
        if not isinstance(volume, dict):
            continue
        chapters = volume.get("chapters", ())
        for chapter in chapters if isinstance(chapters, list) else ():
            if not isinstance(chapter, dict):
                continue
            chapter_id = chapter.get("chapter_id")
            if not isinstance(chapter_id, str) or not chapter_id:
                continue
            for page_id in chapter.get("page_ids", ()) if isinstance(chapter.get("page_ids"), list) else ():
                if isinstance(page_id, str):
                    owners.setdefault(page_id, []).append(chapter_id)
    return owners


def validate_editorial_state(
    state: BookEditorialState,
    *,
    page_ids: set[str] | None = None,
) -> tuple[str, ...]:
    """Return deterministic validation errors; never infer a valid state."""
    errors: list[str] = []
    book = state.book
    curation = state.curation
    outline = state.outline
    paths = state.paths

    if book.get("schema_version") != BOOK_SCHEMA_VERSION:
        errors.append("book-schema-version")
    if curation.get("schema_version") != CURATION_SCHEMA_VERSION:
        errors.append("curation-schema-version")
    if outline.get("schema_version") != OUTLINE_SCHEMA_VERSION:
        errors.append("outline-schema-version")
    if paths.get("schema_version") != PATH_SCHEMA_VERSION:
        errors.append("paths-schema-version")
    book_id = book.get("book_id")
    if not isinstance(book_id, str) or not book_id:
        errors.append("book-id")
    if curation.get("book_id") != book_id or outline.get("book_id") != book_id or paths.get("book_id") != book_id:
        errors.append("book-id-mismatch")
    if book.get("body_policy") != BODY_POLICY:
        errors.append("body-policy")
    if book.get("book_freshness") not in FRESHNESS_STATES:
        errors.append("book-freshness")

    chapter_ids = _chapter_ids(outline)
    all_chapter_ids = _all_chapter_ids(outline)
    if len(all_chapter_ids) != len(chapter_ids):
        duplicates = sorted(chapter_id for chapter_id in all_chapter_ids if all_chapter_ids.count(chapter_id) > 1)
        errors.extend(f"duplicate-chapter:{chapter_id}" for chapter_id in set(duplicates))
    if not isinstance(outline.get("volumes"), list):
        errors.append("outline-volumes")
    pages = curation.get("pages")
    if not isinstance(pages, list):
        errors.append("curation-pages")
        pages = []
    seen_pages: set[str] = set()
    for row in pages:
        if not isinstance(row, dict):
            errors.append("page-disposition-type")
            continue
        page_id = row.get("page_id")
        if not isinstance(page_id, str) or not page_id:
            errors.append("page-id")
            continue
        if page_id in seen_pages:
            errors.append(f"duplicate-disposition:{page_id}")
        seen_pages.add(page_id)
        if page_ids is not None and page_id not in page_ids:
            errors.append(f"unknown-page:{page_id}")
        disposition = row.get("disposition")
        if disposition not in DISPOSITIONS:
            errors.append(f"disposition:{page_id}")
        primary = row.get("primary_chapter_id")
        if disposition in {"include", "conflict"} and primary not in chapter_ids:
            errors.append(f"primary-chapter:{page_id}")
        secondary = row.get("secondary_references", [])
        if not isinstance(secondary, list) or any(item not in chapter_ids for item in secondary):
            errors.append(f"secondary-reference:{page_id}")
        if disposition in {"include", "conflict"} and not isinstance(row.get("content_hash_at_review"), str):
            errors.append(f"content-hash:{page_id}")

    path_rows = paths.get("paths")
    if not isinstance(path_rows, list):
        errors.append("paths-list")
        path_rows = []
    for row in path_rows:
        if not isinstance(row, dict):
            errors.append("path-type")
            continue
        path_id = row.get("path_id")
        if not isinstance(path_id, str) or not path_id:
            errors.append("path-id")
        if "body" in row:
            errors.append(f"path-body-forbidden:{path_id or '<missing>'}")
    errors.extend(validate_tutorial_paths(paths, outline))
    owners = _outline_page_owners(outline)
    dispositions = {
        row.get("page_id"): row
        for row in pages
        if isinstance(row, dict) and isinstance(row.get("page_id"), str)
    }
    for page_id, owners_for_page in sorted(owners.items()):
        if len(set(owners_for_page)) > 1:
            errors.append(f"multiple-outline-owners:{page_id}")
        row = dispositions.get(page_id)
        if row is None:
            errors.append(f"missing-disposition:{page_id}")
        elif row.get("disposition") not in {"include", "conflict"}:
            errors.append(f"outline-disposition:{page_id}")
    return tuple(sorted(set(errors)))


def build_editorial_state(
    snapshot: WikiSnapshot,
    *,
    book_id: str,
    outline: dict[str, Any],
    project_id: str = "novel-wiki",
    domain_id: str = "novel-wiki",
    editorial_revision: int = 1,
) -> BookEditorialState:
    """Build deterministic page dispositions from a persisted outline."""
    if not book_id:
        raise ValueError("book_id is required")
    outline_copy = copy.deepcopy(outline)
    outline_copy.setdefault("schema_version", OUTLINE_SCHEMA_VERSION)
    outline_copy["book_id"] = book_id
    outline_copy["editorial_revision"] = editorial_revision
    outline_copy["snapshot_id"] = snapshot.snapshot_id
    owners = _outline_page_owners(outline_copy)
    seen_snapshot_ids: set[str] = set()
    rows: list[dict[str, Any]] = []
    for page in sorted(snapshot.pages, key=lambda item: item.page_id):
        owners_for_page = owners.get(page.page_id, [])
        if page.page_id in seen_snapshot_ids:
            disposition, primary, reason = "unresolved", None, "duplicate-page-id"
        elif len(set(owners_for_page)) > 1:
            disposition, primary, reason = "unresolved", None, "multiple-outline-owners"
        elif len(owners_for_page) == 1:
            disposition, primary, reason = "include", owners_for_page[0], "outline-assignment"
        else:
            disposition, primary, reason = "unresolved", None, "not-in-outline"
        seen_snapshot_ids.add(page.page_id)
        rows.append({
            "page_id": page.page_id,
            "disposition": disposition,
            "primary_chapter_id": primary,
            "secondary_references": [],
            "reason": reason,
            "content_hash_at_review": page.content_sha256,
        })

    book = {
        "schema_version": BOOK_SCHEMA_VERSION,
        "project_id": project_id,
        "domain_id": domain_id,
        "book_id": book_id,
        "body_policy": BODY_POLICY,
        "editorial_revision": editorial_revision,
        "source_snapshot_id": snapshot.snapshot_id,
        "book_freshness": "fresh",
    }
    curation = {
        "schema_version": CURATION_SCHEMA_VERSION,
        "project_id": project_id,
        "domain_id": domain_id,
        "book_id": book_id,
        "editorial_revision": editorial_revision,
        "source_snapshot_id": snapshot.snapshot_id,
        "pages": rows,
    }
    paths = {
        "schema_version": PATH_SCHEMA_VERSION,
        "domain_id": domain_id,
        "book_id": book_id,
        "editorial_revision": editorial_revision,
        "paths": [],
    }
    state = BookEditorialState(book, curation, outline_copy, paths)
    errors = validate_editorial_state(state, page_ids={page.page_id for page in snapshot.pages})
    if errors:
        raise ValueError("invalid editorial state: " + ", ".join(errors))
    return state


def save_editorial_state(book_root: str | Path, state: BookEditorialState) -> None:
    root = Path(book_root)
    errors = validate_editorial_state(state)
    if errors:
        raise ValueError("invalid editorial state: " + ", ".join(errors))
    payloads = {
        "book.json": state.book,
        "editorial/curation.json": state.curation,
        "editorial/outline.json": state.outline,
        "editorial/paths.json": state.paths,
    }
    for relative, payload in payloads.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_canonical(payload) + b"\n")


def load_editorial_state(book_root: str | Path) -> BookEditorialState:
    root = Path(book_root)

    def read(relative: str) -> dict[str, Any]:
        payload = json.loads((root / relative).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"{relative} must contain an object")
        return payload

    state = BookEditorialState(
        read("book.json"),
        read("editorial/curation.json"),
        read("editorial/outline.json"),
        read("editorial/paths.json"),
    )
    errors = validate_editorial_state(state)
    if errors:
        raise ValueError("invalid editorial state: " + ", ".join(errors))
    return state


__all__ = [
    "BOOK_SCHEMA_VERSION", "CURATION_SCHEMA_VERSION", "OUTLINE_SCHEMA_VERSION",
    "PATH_SCHEMA_VERSION", "BODY_POLICY", "DISPOSITIONS", "FRESHNESS_STATES",
    "BookEditorialState", "build_editorial_state", "editorial_state_hash",
    "load_editorial_state", "save_editorial_state", "validate_editorial_state",
]
