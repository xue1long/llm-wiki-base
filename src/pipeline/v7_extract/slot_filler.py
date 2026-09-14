"""Stage 5: fill the five required concept-page slots."""
from __future__ import annotations

import asyncio
import inspect
import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from .topic_clusterer import Topic


CONCEPT_SLOTS: tuple[str, ...] = (
    "definition",
    "characteristics",
    "examples",
    "related_concepts",
    "references",
)

_SLOT_HEADINGS = {
    "definition": "定义",
    "characteristics": "特征",
    "examples": "例子",
    "related_concepts": "相关概念",
    "references": "参考来源",
}


@dataclass(eq=True)
class ConceptPage:
    """Structured concept page produced before the writer stage."""

    id: str
    title: str
    slots: dict[str, str]
    sources: list[str] = field(default_factory=list)
    type: str = "concept"

    @property
    def body(self) -> str:
        return "\n\n".join(
            f"## {_SLOT_HEADINGS[name]}\n{self.slots[name]}"
            for name in CONCEPT_SLOTS
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "type": self.type,
            "sources": list(self.sources),
            "slots": dict(self.slots),
            "body": self.body,
        }


def fill_slots(
    topic: Topic | Mapping[str, Any] | Any,
    template: Any = None,
    *,
    source_text: str = "",
    llm: Any = None,
) -> ConceptPage:
    """Fill all required concept slots from a topic and source text.

    ``template`` is accepted as a future-compatible input.  When it is a
    mapping with ``slots`` or ``required_slots``, those names are used, but
    the V7 concept contract remains the default five-slot set.
    """
    topic_id, title, sources = _topic_parts(topic)
    slot_names = _slot_names(template)
    slots: dict[str, str] = {}
    if llm is not None:
        slots = _fill_with_llm(
            topic_id, title, sources, source_text, slot_names, llm
        )
    for name in slot_names:
        slots.setdefault(name, _fallback_slot(name, title, source_text, sources))
    # Never leak model-invented keys into the page body.
    slots = {name: str(slots.get(name, "")).strip() for name in slot_names}
    return ConceptPage(topic_id, title, slots, sources)


def _fill_with_llm(
    topic_id: str,
    title: str,
    sources: list[str],
    source_text: str,
    slot_names: tuple[str, ...],
    llm: Any,
) -> dict[str, str]:
    try:
        response = llm.complete(
            prompt_kind="fill_slots",
            user_prompt=(
                "根据来源内容填写 concept 页的必填槽位。只返回 JSON，格式为 "
                '{"slots":{"definition":"...",...}}。禁止编造来源中没有的事实。\n'
                f"主题：{title}\n素材 ID：{', '.join(sources)}\n"
                f"来源内容：{source_text[:12000]}"
            ),
            system_prompt="每个槽位都必须有非空内容，只输出 JSON。",
            max_tokens=4096,
            temperature=0.0,
        )
        if inspect.isawaitable(response):
            response = asyncio.run(response)
        payload = json.loads(_strip_json_fence(str(response)))
        raw_slots = payload.get("slots", {})
        if not isinstance(raw_slots, dict):
            return {}
        return {
            name: str(raw_slots[name]).strip()
            for name in slot_names
            if raw_slots.get(name)
        }
    except (TypeError, ValueError, KeyError, RuntimeError):
        return {}


def _topic_parts(topic: Any) -> tuple[str, str, list[str]]:
    if isinstance(topic, Mapping):
        topic_id = topic.get("id", "topic")
        title = topic.get("title", topic.get("name", topic_id))
        sources = topic.get("item_ids", topic.get("sources", []))
    else:
        topic_id = getattr(topic, "id", "topic")
        title = getattr(topic, "title", topic_id)
        sources = getattr(topic, "item_ids", getattr(topic, "sources", []))
    return str(topic_id), str(title), [str(value) for value in sources]


def _slot_names(template: Any) -> tuple[str, ...]:
    if not isinstance(template, Mapping):
        return CONCEPT_SLOTS
    names = template.get("required_slots", template.get("slots"))
    if isinstance(names, Mapping):
        names = names.keys()
    if isinstance(names, (list, tuple, set)):
        selected = tuple(str(name) for name in names if str(name) in CONCEPT_SLOTS)
        if selected:
            return selected
    return CONCEPT_SLOTS


def _fallback_slot(name: str, title: str, source_text: str, sources: list[str]) -> str:
    source = source_text.strip()
    if name == "definition":
        return source.split("。", 1)[0].strip("。 ") or f"{title}：来源未提供明确的定义。"
    if name == "characteristics":
        return f"围绕“{title}”整理来源中的关键特征；需结合原文核对。"
    if name == "examples":
        return "来源未提供可独立核验的具体例子。"
    if name == "related_concepts":
        return "来源未提供明确的相关概念。"
    return "参考来源：" + (", ".join(sources) or "当前素材")


def _strip_json_fence(text: str) -> str:
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    return match.group(1) if match else text.strip()
