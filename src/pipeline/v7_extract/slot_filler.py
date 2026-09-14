"""Stage 5: fill the five required concept-page slots.

This stage enforces the boundary from
``docs/superpowers/reports/2026-09-14-v7-script-vs-llm-boundary.md``:

* The LLM produces the **content** for each slot (it can include a small
  amount of Markdown such as bullet lists or inline code).
* The script **validates** the JSON structure, enforces the evidence
  contract (each slot must trace back to a source item or to the
  raw text), and replaces any placeholder / template wording with an
  explicit ``needs_review`` flag.
* Page IDs, frontmatter, template rendering, and Markdown assembly
  remain in the script — the LLM never emits page IDs.

Slot evidence contract
----------------------

For each slot we record either:

* an ``item_id`` from the topic's ``item_ids`` list, or
* a ``source_text_excerpt`` — a literal substring from the source that
  the LLM claims backs the slot.

When neither is present, or the slot's body matches a forbidden
placeholder pattern (``需结合原文核对`` / ``来源未提供明确……`` / …),
the slot is marked ``needs_review`` and the page reports it as
``partial`` — never auto-written to production wiki.
"""
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

# Forbidden placeholder strings. Any slot whose body matches one of these
# is treated as empty / unverifiable evidence and triggers needs_review.
_FORBIDDEN_PLACEHOLDERS = (
    "需结合原文核对",
    "需结合原文",
    "来源未提供明确",
    "来源未提供",
    "未提供",
    "无法确定",
    "无法核实",
    "暂无",
    "占位",
    "N/A", "n/a",
)

# Slot bodies may include a small amount of Markdown: bullet lists, bold,
# italic, inline code, links. We allow a generous cap (16 KB) so real
# LLM responses survive but trivial placeholders are bounded.
_MAX_SLOT_BYTES = 16_384


@dataclass
class SlotEvidence:
    """Evidence trail for a single slot."""

    item_id: str = ""
    source_text_excerpt: str = ""
    has_evidence: bool = False
    needs_review: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "source_text_excerpt": self.source_text_excerpt,
            "has_evidence": self.has_evidence,
            "needs_review": self.needs_review,
        }


@dataclass
class Slot:
    """One filled slot with its evidence trail."""

    name: str
    body: str
    evidence: SlotEvidence = field(default_factory=SlotEvidence)
    needs_review: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "body": self.body,
            "needs_review": self.needs_review,
            "evidence": self.evidence.to_dict(),
        }


@dataclass(eq=True)
class ConceptPage:
    """Structured concept page produced before the writer stage.

    ``slots`` keeps the canonical 5-slot payload. ``needs_review_slots``
    records which slots lacked real evidence — the writer stage uses
    this to refuse auto-publishing partial pages.
    """

    id: str
    title: str
    slots: dict[str, str]
    sources: list[str] = field(default_factory=list)
    type: str = "concept"
    slot_evidence: dict[str, Slot] = field(default_factory=dict)
    needs_review_slots: tuple[str, ...] = ()

    @property
    def body(self) -> str:
        return "\n\n".join(
            f"## {_SLOT_HEADINGS[name]}\n{self.slots[name]}"
            for name in CONCEPT_SLOTS
        )

    @property
    def has_evidence(self) -> bool:
        return bool(self.slot_evidence) and all(
            not slot.needs_review for slot in self.slot_evidence.values()
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "type": self.type,
            "sources": list(self.sources),
            "slots": dict(self.slots),
            "needs_review_slots": list(self.needs_review_slots),
            "has_evidence": self.has_evidence,
            "body": self.body,
        }


def fill_slots(
    topic: Topic | Mapping[str, Any] | Any,
    template: Any = None,
    *,
    source_text: str = "",
    llm: Any = None,
    item_texts: Mapping[str, str] | None = None,
) -> ConceptPage:
    """Fill all required concept slots from a topic and source text.

    ``template`` is accepted as a future-compatible input. When it is a
    mapping with ``slots`` or ``required_slots``, those names are used, but
    the V7 concept contract remains the default five-slot set.

    ``item_texts`` is an optional ``{item_id: text}`` mapping that the
    validator uses to attach ``item_id`` evidence when the LLM response
    cites a specific source item.
    """
    topic_id, title, sources = _topic_parts(topic)
    slot_names = _slot_names(template)
    raw_slots, raw_evidence = _fill_with_llm_or_empty(
        topic_id, title, sources, source_text, slot_names, llm
    )
    slot_map: dict[str, Slot] = {}
    for name in slot_names:
        body = raw_slots.get(name, "")
        evidence = _build_evidence(
            name=name,
            raw_evidence=raw_evidence.get(name, {}),
            item_texts=item_texts or {},
            available_items=sources,
            source_text=source_text,
            body=body,
        )
        slot = Slot(name=slugify_slot(name), body=body, evidence=evidence)
        slot.needs_review = evidence.needs_review
        slot_map[name] = slot
    return _assemble_page(topic_id, title, sources, slot_names, slot_map)


# ---------------------------------------------------------------------------
# LLM invocation
# ---------------------------------------------------------------------------

def _fill_with_llm_or_empty(
    topic_id: str,
    title: str,
    sources: list[str],
    source_text: str,
    slot_names: tuple[str, ...],
    llm: Any,
) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    """Return (slot_bodies, slot_evidence) — both empty when llm is None
    or the response fails validation."""
    if llm is None:
        return {}, {}
    try:
        response = llm.complete(
            prompt_kind="fill_slots",
            user_prompt=_build_slot_prompt(title, sources, source_text, slot_names),
            system_prompt=(
                "为 concept 页填写必填槽位。每个槽位必须给出对应素材 ID "
                "(item_id) 或原文摘录 (source_text_excerpt) 作为证据。"
                "只输出严格 JSON，禁止编造来源中没有的事实。"
            ),
            max_tokens=4096,
            temperature=0.0,
        )
        if inspect.isawaitable(response):
            response = asyncio.run(response)
        payload = json.loads(_strip_json_fence(str(response)))
        if not isinstance(payload, dict):
            return {}, {}
        raw_slots = payload.get("slots", {})
        raw_evidence = payload.get("evidence", {})
        if not isinstance(raw_slots, dict):
            raw_slots = {}
        if not isinstance(raw_evidence, dict):
            raw_evidence = {}
        slots: dict[str, str] = {}
        for name in slot_names:
            value = raw_slots.get(name)
            if isinstance(value, str) and value.strip():
                slots[name] = value.strip()[:_MAX_SLOT_BYTES]
        evidence: dict[str, dict[str, Any]] = {}
        for name in slot_names:
            value = raw_evidence.get(name)
            if isinstance(value, dict):
                evidence[name] = {
                    "item_id": str(value.get("item_id", "") or ""),
                    "source_text_excerpt": str(value.get("source_text_excerpt", "") or ""),
                }
        return slots, evidence
    except (TypeError, ValueError, KeyError, RuntimeError):
        return {}, {}


def _build_slot_prompt(
    title: str,
    sources: list[str],
    source_text: str,
    slot_names: tuple[str, ...],
) -> str:
    slot_list = ", ".join(slot_names)
    return (
        "根据来源内容填写 concept 页的必填槽位。"
        "每个槽位必须附带 evidence 字段（item_id 或 source_text_excerpt）。"
        "只输出严格 JSON，格式：\n"
        '{"slots": {"<slot>": "<text>", ...}, '
        '"evidence": {"<slot>": {"item_id": "...", "source_text_excerpt": "..."}}}\n'
        f"槽位：{slot_list}\n"
        f"主题：{title}\n"
        f"素材 ID：{', '.join(sources)}\n"
        f"来源内容：{source_text[:12000]}"
    )


# ---------------------------------------------------------------------------
# Evidence & placeholder validation
# ---------------------------------------------------------------------------

def _build_evidence(
    *,
    name: str,
    raw_evidence: dict[str, Any],
    item_texts: Mapping[str, str],
    available_items: list[str],
    source_text: str,
    body: str,
) -> SlotEvidence:
    """Validate one slot's evidence trail.

    Evidence is accepted when:
      * the LLM cited a known item_id whose text is provided, OR
      * the LLM cited a literal excerpt that appears in the source text.

    A slot is also flagged needs_review when its body matches a
    forbidden placeholder pattern or is empty.
    """
    evidence = SlotEvidence()
    body_clean = body.strip()
    if _looks_like_placeholder(body_clean) or not body_clean:
        evidence.needs_review = True
        return evidence

    cited_item = raw_evidence.get("item_id", "")
    cited_excerpt = raw_evidence.get("source_text_excerpt", "")

    if cited_item and cited_item in available_items:
        evidence.item_id = cited_item
        evidence.has_evidence = True
        if cited_excerpt:
            evidence.source_text_excerpt = cited_excerpt[:500]
        else:
            # Pull the cited item's text (if provided) as the excerpt.
            text = item_texts.get(cited_item, "")
            if text:
                evidence.source_text_excerpt = text[:500]
        return evidence

    if cited_excerpt and _excerpt_in_source(cited_excerpt, source_text):
        evidence.source_text_excerpt = cited_excerpt[:500]
        evidence.has_evidence = True
        return evidence

    # LLM gave content but no evidence — search for an item whose text
    # appears in the slot body. If found, attach that item as evidence.
    matched_item = _find_item_for_body(body_clean, item_texts)
    if matched_item is not None:
        evidence.item_id = matched_item
        evidence.has_evidence = True
        return evidence

    # No item found, no excerpt recognised — content is unverifiable.
    evidence.needs_review = True
    return evidence


def _looks_like_placeholder(text: str) -> bool:
    if not text:
        return True
    return any(needle in text for needle in _FORBIDDEN_PLACEHOLDERS)


def _excerpt_in_source(excerpt: str, source_text: str) -> bool:
    if not excerpt or not source_text:
        return False
    return excerpt[:120] in source_text


def _find_item_for_body(body: str, item_texts: Mapping[str, str]) -> str | None:
    """Return an item_id whose text appears inside the slot body, or None.

    A short overlap (>= 12 chars) is enough — long-form slots paraphrase
    the source, so we don't demand byte-for-byte equality.
    """
    if not body or not item_texts:
        return None
    for item_id, text in item_texts.items():
        if not text:
            continue
        snippet = text.strip()[:120]
        if len(snippet) >= 12 and snippet in body:
            return item_id
    return None


def _assemble_page(
    topic_id: str,
    title: str,
    sources: list[str],
    slot_names: tuple[str, ...],
    slot_map: dict[str, Slot],
) -> ConceptPage:
    """Finalise the page and compute needs_review_slots / evidence flags."""
    slots: dict[str, str] = {}
    for name in slot_names:
        slots[name] = slot_map[name].body
    needs_review = tuple(
        name for name in slot_names if slot_map[name].evidence.needs_review
    )
    return ConceptPage(
        id=topic_id,
        title=title,
        slots=slots,
        sources=list(sources),
        slot_evidence={
            name: slot_map[name] for name in slot_names
        },
        needs_review_slots=needs_review,
    )


def slugify_slot(name: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_") or "slot"


# ---------------------------------------------------------------------------
# Helpers (kept for backward-compat with scripts that introspect pages)
# ---------------------------------------------------------------------------

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


def _strip_json_fence(text: str) -> str:
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    return match.group(1) if match else text.strip()
