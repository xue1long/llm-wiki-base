"""Stage 6: extract typed relations between generated concept pages."""
from __future__ import annotations

import asyncio
import inspect
import json
import re
from dataclasses import dataclass
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


def extract_relations(pages: list[Any], *, llm: Any = None) -> list[PageRelation]:
    """Return deduplicated, validated relations between ``pages``.

    The extractor currently focuses on the two V7 relations with clear
    semantics: ``refines`` for a more specific method and ``supported_by``
    for a concept grounded by another page.
    """
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
