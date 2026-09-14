"""Stage 4 concept de-duplication.

The operation is intentionally a pure merge: existing ids and source ids are
preserved, while genuinely new collisions receive a stable numeric suffix.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass(eq=True)
class ConceptCandidate:
    id: str
    title: str
    source_ids: list[str] = field(default_factory=list)
    body: str = ""


def deduplicate_concepts(
    concepts: Iterable[Any],
    *,
    existing_concepts: Iterable[Any] | None = None,
    existing_ids: Iterable[str] | None = None,
) -> list[ConceptCandidate]:
    """Merge candidates into existing concepts and make new ids collision-safe.

    A candidate merges when its id or normalized title matches an existing
    concept.  Source ids are unioned in first-seen order, making a second run
    idempotent.  ``existing_ids`` is accepted for callers that only have an
    index of ids and need collision-safe new ids.
    """
    result = [_coerce(candidate) for candidate in (existing_concepts or [])]
    reserved = {concept.id for concept in result}
    reserved.update(str(value) for value in (existing_ids or []))
    # Only concepts that existed before this call are merge targets.  A
    # repeated candidate in the same batch is a distinct new candidate and
    # receives a suffix; this also makes repeated runs idempotent.
    merge_by_id = {concept.id: concept for concept in result}
    merge_by_title = {_title_key(concept.title): concept for concept in result}

    for raw in concepts:
        candidate = _coerce(raw)
        match = merge_by_id.get(candidate.id) or merge_by_title.get(_title_key(candidate.title))
        if match is not None:
            _merge(match, candidate)
            continue

        candidate.id = _unique_id(candidate.id, reserved)
        reserved.add(candidate.id)
        result.append(candidate)
    return result


def _coerce(value: Any) -> ConceptCandidate:
    if isinstance(value, ConceptCandidate):
        return ConceptCandidate(value.id, value.title, list(value.source_ids), value.body)
    if isinstance(value, dict):
        return ConceptCandidate(
            id=str(value.get("id", "concept")),
            title=str(value.get("title", value.get("name", ""))),
            source_ids=[str(item) for item in value.get("source_ids", value.get("sources", []))],
            body=str(value.get("body", "")),
        )
    return ConceptCandidate(
        id=str(getattr(value, "id", "concept")),
        title=str(getattr(value, "title", "")),
        source_ids=[str(item) for item in getattr(value, "source_ids", [])],
        body=str(getattr(value, "body", "")),
    )


def _merge(target: ConceptCandidate, incoming: ConceptCandidate) -> None:
    for source_id in incoming.source_ids:
        if source_id not in target.source_ids:
            target.source_ids.append(source_id)
    if not target.body and incoming.body:
        target.body = incoming.body


def _title_key(title: str) -> str:
    return "".join(str(title).casefold().split())


def _unique_id(base: str, reserved: set[str]) -> str:
    if base not in reserved:
        return base
    suffix = 2
    while f"{base}-{suffix}" in reserved:
        suffix += 1
    return f"{base}-{suffix}"
