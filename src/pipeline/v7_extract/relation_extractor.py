"""Stage 6: extract typed relations between generated concept pages."""
from __future__ import annotations

import asyncio
import inspect
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


ALLOWED_RELATION_TYPES = frozenset({"refines", "supported_by"})


@dataclass(eq=True, frozen=True)
class PageRelation:
    source_id: str
    target_id: str
    type: str
    weight: float = 1.0
    context: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target_id,
            "type": self.type,
            "weight": round(self.weight, 2),
            "context": self.context,
        }


# A convenient short name for callers that do not need the more explicit
# PageRelation spelling.
Relation = PageRelation


def extract_relations(
    pages: list[Any],
    *,
    llm: Any = None,
    project_root: Path | str | None = None,
    index: Any = None,
    vector_neighbors: dict[str, list[tuple[str, float]]] | None = None,
    max_candidates: int = 30,
) -> list[PageRelation]:
    """Return deduplicated, validated relations between ``pages``.

    Refactored in Task 25 to support the new ``PageIndex``-driven
    retrieval pipeline. Two execution paths:

    * When ``index`` is provided, the function delegates to
      ``_extract_with_ontology`` — bounded candidate retrieval + LLM
      over the controlled predicate whitelist. This is the production
      path; it scales O(N·C) rather than O(N²).
    * When ``index is None`` (the legacy / tests path), the function
      falls back to the v1 pairwise heuristic or the v1 LLM prompt —
      preserved verbatim so the existing 3 stage6 tests stay green.

    The returned ``PageRelation`` shape is unchanged — Task 25 only
    changes *how* the candidates are found, not the contract callers
    downstream of this function rely on.
    """
    if index is not None:
        return _extract_with_ontology(
            pages,
            index=index,
            llm=llm,
            vector_neighbors=vector_neighbors,
            max_candidates=max_candidates,
        )

    page_data = [_page_parts(page) for page in pages]
    page_ids = {page_id for page_id, _, _ in page_data}
    if llm is not None:
        raw = _extract_with_llm(page_data, llm)
        if raw is not None:
            return _deduplicate(
                relation
                for relation in raw
                if relation.source_id in page_ids
                and relation.target_id in page_ids
                and relation.source_id != relation.target_id
                and relation.type in ALLOWED_RELATION_TYPES
            )
    return _heuristic_relations(page_data)


def _extract_with_ontology(
    pages: list[Any],
    *,
    index: Any,
    llm: Any | None,
    vector_neighbors: dict[str, list[tuple[str, float]]] | None,
    max_candidates: int,
) -> list[PageRelation]:
    """New (Task 25) path: build a PageIndex over ``pages`` (if needed),
    run candidate retrieval per source page, optionally call the LLM
    with the controlled-ontology prompt, then map ``RelationAssertion``
    rows back to ``PageRelation`` for the legacy contract.

    Falls back gracefully when no ``llm`` is wired — we just return the
    top retrieval candidates as ``supported_by`` edges (no type guessing
    without LLM involvement). The deterministic ``refines`` /
    ``supported_by`` split from v1 only applied when the LLM was
    present; in the index-only mode we keep the semantics simple.
    """
    # Local import — keeps the candidate_retrieval dependency optional
    # so legacy callers that don't import the new module don't pull it.
    from .candidate_retrieval import (
        PageIndex as _PageIndex,
        retrieve_candidates,
    )

    if not isinstance(index, _PageIndex):
        # Be tolerant: if a foreign PageIndex-like object was passed,
        # build one over the supplied pages so the strategy still works.
        index = _PageIndex.build(pages)

    relations: list[PageRelation] = []
    seen: set[tuple[str, str, str]] = set()

    for page in pages:
        page_id = str(getattr(page, "id", "") or "")
        if not page_id or page_id not in index.pages:
            continue
        source_entry = index.get(page_id)
        if source_entry is None:
            continue
        neighbors = (vector_neighbors or {}).get(page_id)
        candidates = retrieve_candidates(
            page_id,
            index,
            max_candidates=max_candidates,
            vector_neighbors=neighbors,
        )

        # Path A: LLM present — parse controlled JSON edges.
        if llm is not None:
            assertions = _invoke_ontology_llm(
                llm, source_entry, candidates
            )
            for assertion in assertions:
                # Map only SUPPORTED rows (REJECTED / UNRESOLVED are
                # surfaced through the RelationStore, not the legacy
                # PageRelation contract).
                if (
                    assertion.support_status.value != "supported"
                    or assertion.key.predicate.value == "unresolved"
                ):
                    continue
                rel_type = str(assertion.key.predicate.value)
                if rel_type not in ALLOWED_RELATION_TYPES:
                    # LLM-direct edges outside the legacy whitelist are
                    # only honored when callers opt-in via the new
                    # module. Keep the legacy contract narrow.
                    continue
                key = (page_id, assertion.key.target_page_id, rel_type)
                if key in seen:
                    continue
                seen.add(key)
                relations.append(
                    PageRelation(
                        source_id=page_id,
                        target_id=str(assertion.key.target_page_id),
                        type=rel_type,
                        weight=float(assertion.confidence),
                        context="llm_direct",
                    )
                )
            continue

        # Path B: no LLM — top candidates become "supported_by" edges.
        for cand in candidates[:max_candidates]:
            key = (page_id, cand.target_page_id, "supported_by")
            if key in seen:
                continue
            seen.add(key)
            relations.append(
                PageRelation(
                    source_id=page_id,
                    target_id=cand.target_page_id,
                    type="supported_by",
                    weight=round(cand.score, 2),
                    context=cand.kind.value,
                )
            )

    return relations


def _invoke_ontology_llm(llm: Any, source_entry: Any, candidates: list[Any]) -> list[Any]:
    """Call the LLM with the controlled-ontology prompt, parse the JSON
    response, and return the resulting ``RelationAssertion`` rows.

    Failures (LLM exception, malformed JSON, etc.) yield an empty list
    rather than raising — the legacy ``extract_relations`` semantics
    treated LLM errors as "fall back to heuristic", and we keep that
    behavior here so a flaky LLM doesn't kill the whole batch.
    """
    # Imports here to keep top-level module import cheap when callers
    # don't exercise the ontology path.
    from .candidate_retrieval import (
        parse_llm_edges,
        render_llm_prompt,
    )

    try:
        prompt = render_llm_prompt(source_entry, candidates)
        response = llm.complete(
            prompt_kind="extract_relations_ontology",
            user_prompt=prompt,
            system_prompt=(
                "Output only JSON. Use ONLY predicates from the allowed list."
            ),
            max_tokens=2048,
            temperature=0.0,
        )
        if inspect.isawaitable(response):
            response = asyncio.run(response)
        return parse_llm_edges(
            str(response),
            source_page_id=source_entry.page_id,
            candidates=candidates,
            extractor_fingerprint="relation_extractor.v2",
        )
    except (TypeError, ValueError, KeyError, RuntimeError, AttributeError):
        return []


def _extract_with_llm(
    pages: list[tuple[str, str, dict[str, str]]], llm: Any
) -> list[PageRelation] | None:
    prompt = "\n".join(
        f"{page_id} [{title}]: {json.dumps(slots, ensure_ascii=False)}"
        for page_id, title, slots in pages
    )
    try:
        response = llm.complete(
            prompt_kind="extract_relations",
            user_prompt=(
                "从 concept 页之间抽取关系，只允许 refines 或 supported_by。"
                '只返回 JSON：{"relations":[{"source_id":"...",'
                '"target_id":"...","type":"refines|supported_by",'
                '"context":"..."}]}。\n' + prompt
            ),
            system_prompt="只输出 JSON；过滤自环、未知页面和不支持的关系类型。",
            max_tokens=4096,
            temperature=0.0,
        )
        if inspect.isawaitable(response):
            response = asyncio.run(response)
        payload = json.loads(_strip_json_fence(str(response)))
        raw_relations = payload.get("relations", [])
        if not isinstance(raw_relations, list):
            return []
        result = []
        for raw in raw_relations:
            if not isinstance(raw, Mapping):
                continue
            result.append(
                PageRelation(
                    str(raw.get("source_id", "")),
                    str(raw.get("target_id", "")),
                    str(raw.get("type", "")),
                    float(raw.get("weight", 1.0)),
                    str(raw.get("context", "")),
                )
            )
        return result
    except (TypeError, ValueError, KeyError, RuntimeError):
        return None


def _heuristic_relations(
    pages: list[tuple[str, str, dict[str, str]]]
) -> list[PageRelation]:
    result: list[PageRelation] = []
    for source_id, source_title, source_slots in pages:
        searchable = " ".join([source_title, *source_slots.values()])
        for target_id, target_title, _ in pages:
            if source_id == target_id or not (
                target_id in searchable or target_title in searchable
            ):
                continue
            refinement = any(
                marker in source_title or marker in source_slots.get("characteristics", "")
                for marker in ("进阶", "高级", "场景", "细化", "基础上", "扩展")
            )
            relation_type = "refines" if refinement else "supported_by"
            result.append(PageRelation(source_id, target_id, relation_type))
    return _deduplicate(result)


def _deduplicate(relations: Any) -> list[PageRelation]:
    result: list[PageRelation] = []
    seen: set[tuple[str, str, str]] = set()
    for relation in relations:
        key = (relation.source_id, relation.target_id, relation.type)
        if key in seen:
            continue
        seen.add(key)
        result.append(relation)
    return result


def _page_parts(page: Any) -> tuple[str, str, dict[str, str]]:
    if isinstance(page, Mapping):
        page_id = page.get("id", "")
        title = page.get("title", page_id)
        slots = page.get("slots", {})
    else:
        page_id = getattr(page, "id", "")
        title = getattr(page, "title", page_id)
        slots = getattr(page, "slots", {})
    return str(page_id), str(title), {str(k): str(v) for k, v in (slots or {}).items()}


def _strip_json_fence(text: str) -> str:
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    return match.group(1) if match else text.strip()
