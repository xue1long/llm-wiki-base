"""Fail-closed schema and stable page-ID coverage checks for outlines."""
from __future__ import annotations

import math
from collections import Counter
from .model import WikiSnapshot
from .outline_model import PageAssignment, ValidationError, ValidationReport

SCHEMA_VERSION = "outline-v1"
ROLES = frozenset({"core", "method", "pitfall", "case", "reference"})


def _error(code: str, message: str, context: str | None = None) -> ValidationError:
    return ValidationError(code, message, context)


def validate_outline_schema(payload: object) -> tuple[ValidationError, ...]:
    errors: list[ValidationError] = []
    if not isinstance(payload, dict):
        return (_error("schema-type", "outline must be an object", "outline"),)
    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append(_error("schema-version", f"schema_version must be {SCHEMA_VERSION!r}", "outline"))
    if not isinstance(payload.get("snapshot_id"), str) or not payload["snapshot_id"]:
        errors.append(_error("snapshot-id", "snapshot_id must be a non-empty string", "outline"))
    volumes = payload.get("volumes")
    if not isinstance(volumes, list):
        errors.append(_error("volumes-type", "volumes must be a list", "outline"))
        return tuple(errors)
    volume_ids: set[str] = set()
    chapter_ids: set[str] = set()
    for vi, volume in enumerate(volumes):
        ctx = f"volume[{vi}]"
        if not isinstance(volume, dict):
            errors.append(_error("volume-type", "volume must be an object", ctx)); continue
        vid = volume.get("volume_id")
        if not isinstance(vid, str) or not vid:
            errors.append(_error("volume-id", "volume_id must be a non-empty string", ctx))
        elif vid in volume_ids:
            errors.append(_error("duplicate-volume-id", f"duplicate volume id {vid!r}", ctx))
        else:
            volume_ids.add(vid)
        if "title" in volume and not isinstance(volume["title"], str):
            errors.append(_error("volume-title", "title must be a string", ctx))
        if "is_fallback" in volume and not isinstance(volume["is_fallback"], bool):
            errors.append(_error("fallback-type", "is_fallback must be boolean", ctx))
        chapters = volume.get("chapters")
        if not isinstance(chapters, list):
            errors.append(_error("chapters-type", "chapters must be a list", ctx)); continue
        for ci, chapter in enumerate(chapters):
            cctx = f"{ctx}.chapter[{ci}]"
            if not isinstance(chapter, dict):
                errors.append(_error("chapter-type", "chapter must be an object", cctx)); continue
            cid = chapter.get("chapter_id")
            if not isinstance(cid, str) or not cid:
                errors.append(_error("chapter-id", "chapter_id must be a non-empty string", cctx))
            elif cid in chapter_ids:
                errors.append(_error("duplicate-chapter-id", f"duplicate chapter id {cid!r}", cctx))
            else:
                chapter_ids.add(cid)
            if "title" in chapter and not isinstance(chapter["title"], str):
                errors.append(_error("chapter-title", "title must be a string", cctx))
            page_ids = chapter.get("page_ids")
            if not isinstance(page_ids, list) or any(not ((isinstance(i, str) and i) or (isinstance(i, dict) and isinstance(i.get("page_id"), str) and i["page_id"])) for i in page_ids):
                errors.append(_error("page-ids-type", "page_ids must be a list of non-empty strings", cctx))
            refs = chapter.get("overview_refs")
            if not isinstance(refs, list) or not refs or any(not isinstance(i, str) or not i for i in refs):
                errors.append(_error("overview-refs", "overview_refs must be a non-empty list of strings", cctx))
            for key in ("confidence",):
                if key in chapter and (not isinstance(chapter[key], (int, float)) or isinstance(chapter[key], bool) or not math.isfinite(chapter[key]) or not 0 <= chapter[key] <= 1):
                    errors.append(_error("invalid-confidence", "confidence must be finite and in [0, 1]", cctx))
    return tuple(errors)


def _payloads(outlines: list[dict]) -> list[dict]:
    return outlines


def _assignments(outlines: list[dict]) -> tuple[list[PageAssignment], list[ValidationError]]:
    result: list[PageAssignment] = []
    errors: list[ValidationError] = []
    for payload in _payloads(outlines):
        for volume in payload.get("volumes", []) if isinstance(payload, dict) else []:
            if not isinstance(volume, dict):
                continue
            vid = volume.get("volume_id", "")
            for chapter in volume.get("chapters", []) if isinstance(volume.get("chapters"), list) else []:
                if not isinstance(chapter, dict):
                    continue
                cid = chapter.get("chapter_id", "")
                for item in chapter.get("page_ids", []) if isinstance(chapter.get("page_ids"), list) else []:
                    if isinstance(item, str):
                        result.append(PageAssignment(item, vid, cid))
                    elif isinstance(item, dict) and isinstance(item.get("page_id"), str):
                        result.append(PageAssignment(item["page_id"], vid, cid, item.get("role"), item.get("confidence")))
                    else:
                        errors.append(_error("page-id-type", "page assignment must contain page_id", f"chapter:{cid}"))
    return result, errors


def build_page_index(outlines: list[dict]) -> dict[str, PageAssignment]:
    index: dict[str, PageAssignment] = {}
    assignments, errors = _assignments(outlines)
    if errors:
        raise ValueError(errors[0].message)
    for assignment in assignments:
        if assignment.page_id in index:
            raise ValueError(f"duplicate page id {assignment.page_id!r}")
        index[assignment.page_id] = assignment
    return index


def validate_outline(snapshot: WikiSnapshot, outlines: list[dict]) -> ValidationReport:
    errors: list[ValidationError] = []
    for payload in outlines:
        errors.extend(validate_outline_schema(payload))
        if isinstance(payload, dict) and payload.get("snapshot_id") != snapshot.snapshot_id:
            errors.append(_error("snapshot-mismatch", "outline snapshot_id does not match snapshot", "outline"))
    assignments, parse_errors = _assignments(outlines)
    errors.extend(parse_errors)
    page_set = {page.page_id for page in snapshot.pages}
    for payload in outlines:
        for volume in payload.get("volumes", []) if isinstance(payload, dict) else []:
            for chapter in volume.get("chapters", []) if isinstance(volume, dict) and isinstance(volume.get("chapters"), list) else []:
                if not isinstance(chapter, dict):
                    continue
                refs = chapter.get("overview_refs", [])
                if isinstance(refs, list):
                    assigned = {item if isinstance(item, str) else item.get("page_id") for item in chapter.get("page_ids", []) if isinstance(item, (str, dict))}
                    bad = [ref for ref in refs if ref not in assigned or ref not in page_set]
                    if bad:
                        errors.append(_error("invalid-overview-refs", f"overview_refs do not resolve to chapter pages: {bad!r}", f"chapter:{chapter.get('chapter_id', '')}"))
    expected = Counter(page.page_id for page in snapshot.pages)
    actual = Counter(item.page_id for item in assignments)
    for page_id in sorted(expected.keys() - actual.keys()):
        errors.append(_error("missing-id", f"page {page_id!r} is omitted", f"page:{page_id}"))
    for page_id in sorted(actual.keys() - expected.keys()):
        errors.append(_error("unknown-id", f"unknown page id {page_id!r}", f"page:{page_id}"))
    for page_id in sorted((expected & actual).keys()):
        if actual[page_id] > expected[page_id]:
            errors.append(_error("duplicate-id", f"page {page_id!r} assigned more than once", f"page:{page_id}"))
    for item in assignments:
        if item.role is not None and item.role not in ROLES:
            errors.append(_error("invalid-role", f"role {item.role!r} is not allowed", f"page:{item.page_id}"))
        if item.confidence is not None and (not isinstance(item.confidence, (int, float)) or isinstance(item.confidence, bool) or not math.isfinite(item.confidence) or not 0 <= item.confidence <= 1):
            errors.append(_error("invalid-confidence", "confidence must be finite and in [0, 1]", f"page:{item.page_id}"))
    fallback_count = 0
    unclassified = {page.page_id for page in snapshot.pages if not page.primary_taxonomy}
    for payload in outlines:
        for volume in payload.get("volumes", []) if isinstance(payload, dict) else []:
            if isinstance(volume, dict) and volume.get("is_fallback"):
                fallback_count += 1
                if not volume.get("chapters") or not any(ch.get("page_ids") for ch in volume.get("chapters", []) if isinstance(ch, dict)):
                    errors.append(_error("empty-fallback", "fallback volume must contain pages", f"volume:{volume.get('volume_id', '')}"))
                assigned = {
                    item if isinstance(item, str) else item.get("page_id")
                    for chapter in volume.get("chapters", []) if isinstance(chapter, dict)
                    for item in chapter.get("page_ids", []) if isinstance(item, (str, dict))
                }
                if assigned - unclassified:
                    errors.append(_error("fallback-without-unclassified", "fallback volume may contain only unclassified pages", f"volume:{volume.get('volume_id', '')}"))
    if fallback_count > 1:
        errors.append(_error("multiple-fallback", "at most one fallback volume is allowed", "outline"))
    return ValidationReport(not errors, tuple(errors))


__all__ = ["SCHEMA_VERSION", "build_page_index", "validate_outline", "validate_outline_schema"]
