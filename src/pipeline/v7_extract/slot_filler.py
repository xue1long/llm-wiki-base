"""Stage 5 of the V7 extract pipeline: fill the 5 required concept slots.

v3 (plan 2026-09-15): async LLM call with prompts/ templates + D7.

v3.1 (Wave 1 / T1, plan 2026-09-15 control-plane refactor): the LLM
cites evidence by integer ``item_index`` into a script-owned numbered
item list. The script maps each index back to the canonical item id
(``Topic.item_ids[index]``). The LLM no longer invents item ids, and
the source_text_excerpt substring gate was dropped — excerpts stay as
human-review references only.

D7: when this stage fails, return ``None`` — the caller is responsible
for recording the topic as failed (see ``failures.py``) and dropping
it from the page list before passing to WikiWriter.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

from .llm_client import LLMClient
from .prompts.parser import PromptParseError
from .prompts.renderer import (
    LLMResponseError,
    parse_llm_response,
    render_prompt,
)
from .prompts.resolver import PromptNotFoundError, resolve

if TYPE_CHECKING:
    from .prompts.ast import PromptTemplate


log = logging.getLogger(__name__)


# The 5 canonical concept slots. v3 still emits these 5 (matches the
# v2 concept contract); expanding to the full 8-section template is
# tracked separately in plan Task 1 / 2 (out of scope for v3.0).
CONCEPT_SLOTS: tuple[str, ...] = (
    "definition",
    "characteristics",
    "examples",
    "related_concepts",
    "references",
)


_SLOT_HEADINGS: dict[str, str] = {
    "definition": "定义",
    "characteristics": "特征",
    "examples": "例子",
    "related_concepts": "相关概念",
    "references": "参考来源",
}


# Cap on per-item snippet length inside the numbered item list. Keeps
# the prompt bounded while still giving the LLM enough context to cite
# by index.
_ITEM_SNIPPET_LIMIT = 200


def _format_items_text(
    item_ids: list[str],
    item_texts: Mapping[str, Any] | None,
) -> str:
    """Render the numbered item list the LLM cites by zero-based index.

    Each line: ``"<index>: <item_id>\\n<snippet>"``. Empty / missing
    snippets are allowed — the LLM still has the index. ``item_texts``
    may map to either a plain ``str`` (the slice text) or a dict with a
    ``text`` key (Stage 2 output shape).
    """
    items_texts = item_texts or {}
    lines: list[str] = []
    for index, item_id in enumerate(item_ids):
        raw = items_texts.get(item_id, "")
        if isinstance(raw, Mapping):
            snippet = str(raw.get("text", ""))[:_ITEM_SNIPPET_LIMIT]
        else:
            snippet = str(raw)[:_ITEM_SNIPPET_LIMIT]
        lines.append(f"{index}: {item_id}\n{snippet}")
    return "\n\n".join(lines)


@dataclass(frozen=True)
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
    """Structured concept page produced by Stage 5.

    ``slots`` is the canonical 5-slot payload. ``needs_review_slots``
    records which slots lacked real evidence — Stage 7 WikiWriter
    uses this to refuse auto-publishing partial pages.

    v3.1 (T1, plan 2026-09-15 control-plane refactor): ``id`` is the
    Stage-5 internal id (= ``Topic.id`` from Stage 4). ``topic_id`` is
    a separate field that scripts (extract_pilot) populate so downstream
    filters (e.g. ``failures.filter_failed_topics``) can group pages by
    source topic without poking the dataclass via ``__dict__``. Default
    ``None`` preserves the v3 dataclass contract for callers that
    never set it.
    """

    id: str
    title: str
    slots: dict[str, str]
    sources: list[str] = field(default_factory=list)
    type: str = "concept"
    slot_evidence: dict[str, Slot] = field(default_factory=dict)
    needs_review_slots: tuple[str, ...] = ()
    topic_id: str | None = None

    @property
    def body(self) -> str:
        return "\n\n".join(
            f"## {_SLOT_HEADINGS.get(name, name)}\n{self.slots[name]}"
            for name in self.slots
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


async def fill_slots(
    topic: Any,
    source_text: str,
    *,
    llm: LLMClient,
    item_texts: Mapping[str, str] | None = None,
    project_root: Path | str | None = None,
    max_retries: int = 3,
) -> ConceptPage | None:
    """Fill the 5 concept slots from ``source_text``.

    D7: returns ``None`` on any failure (P2 invariant). The caller
    records the topic id in ``failures.filter_failed_topics`` and
    drops it from the pages list.
    """
    topic_id, title, sources = _topic_parts(topic)
    template = _resolve_fill_slots_template(project_root)
    system_prompt, user_prompt = render_prompt(template, {
        "title": title,
        "slot_list": ", ".join(CONCEPT_SLOTS),
        "items_text": _format_items_text(sources, item_texts),
        "source_text": source_text[:12000],
        "content_limit": "12000",
    })

    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            raw = await llm.complete(
                prompt_kind="fill_slots",
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                max_tokens=4096,
                temperature=0.0,
            )
            payload = parse_llm_response(raw, template.output_schema)
            return _payload_to_page(
                payload=payload,
                topic_id=topic_id,
                title=title,
                sources=list(sources),
                item_texts=item_texts or {},
                source_text=source_text,
            )
        except LLMResponseError as e:
            last_error = e
            log.info(
                "fill_slots[%s]: response failed validation (attempt %d/%d): %s",
                topic_id, attempt + 1, max_retries, e,
            )
            continue
        except Exception as e:
            last_error = e
            log.warning(
                "fill_slots[%s]: LLM call failed (attempt %d/%d): %s",
                topic_id, attempt + 1, max_retries, e,
            )
            continue

    log.error(
        "fill_slots[%s]: all %d retries exhausted, returning None. last_error=%r",
        topic_id, max_retries, last_error,
    )
    return None  # D7: caller drops this topic


def _payload_to_page(
    *,
    payload: dict,
    topic_id: str,
    title: str,
    sources: list[str],
    item_texts: Mapping[str, str],
    source_text: str,
) -> ConceptPage:
    """Convert a validated LLM JSON payload into a ConceptPage.

    The output_schema (fill_slots.toml) guarantees ``slots`` and
    ``evidence`` are present. The LLM now cites evidence by zero-based
    ``item_index`` integer into ``sources`` (= Topic.item_ids); the
    script maps ``item_index`` → ``sources[item_index]`` and stores the
    canonical id on ``SlotEvidence.item_id``. Invalid / out-of-range
    indexes fall back to ``needs_review`` with an empty ``item_id``.

    The ``source_text_excerpt`` is preserved as a human-review reference
    but no longer substring-gates the slot (the LLM is allowed to
    paraphrase). Empty body strings also mark the slot ``needs_review``.
    """
    raw_slots = payload.get("slots") or {}
    raw_evidence = payload.get("evidence") or {}
    if not isinstance(raw_slots, dict):
        raw_slots = {}
    if not isinstance(raw_evidence, dict):
        raw_evidence = {}

    slot_map: dict[str, Slot] = {}
    n_sources = len(sources)
    for name in CONCEPT_SLOTS:
        body_raw = raw_slots.get(name, "")
        body = str(body_raw).strip() if body_raw else ""
        ev_dict = raw_evidence.get(name, {})
        if not isinstance(ev_dict, dict):
            ev_dict = {}
        item_id = ""
        index_raw = ev_dict.get("item_index")
        if (
            isinstance(index_raw, bool)
            or not isinstance(index_raw, int)
            or not 0 <= index_raw < n_sources
        ):
            # Invalid / missing index → no canonical evidence.
            pass
        else:
            item_id = str(sources[index_raw])
        excerpt = str(ev_dict.get("source_text_excerpt", "") or "")
        has_evidence = bool(item_id)
        needs_review = (not has_evidence) or (not body)
        ev = SlotEvidence(
            item_id=item_id,
            source_text_excerpt=excerpt[:500],
            has_evidence=has_evidence,
            needs_review=needs_review,
        )
        slot = Slot(name=name, body=body, evidence=ev, needs_review=needs_review)
        slot_map[name] = slot

    needs_review_slots = tuple(
        name for name, slot in slot_map.items() if slot.needs_review
    )
    return ConceptPage(
        id=topic_id,
        title=title,
        slots={n: slot_map[n].body for n in CONCEPT_SLOTS},
        sources=sources,
        slot_evidence=slot_map,
        needs_review_slots=needs_review_slots,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _topic_parts(topic: Any) -> tuple[str, str, list[str]]:
    """Normalise ``topic`` (Topic dataclass / dict / object)."""
    if hasattr(topic, "id") and hasattr(topic, "title"):
        sources = list(getattr(topic, "item_ids", []) or [])
        return str(topic.id), str(topic.title), sources
    if isinstance(topic, Mapping):
        return (
            str(topic.get("id", "")),
            str(topic.get("title", "")),
            [str(s) for s in topic.get("item_ids", []) or []],
        )
    # Generic object: try attribute access
    sources = list(getattr(topic, "item_ids", []) or [])
    return str(getattr(topic, "id", "")), str(getattr(topic, "title", "")), sources


def _excerpt_in_source(excerpt: str, source_text: str) -> bool:
    """v2 rule: the cited excerpt must literally appear in the source.

    Case-insensitive (the LLM may normalise casing). We don't require
    full-text match (LLM may trim whitespace), but a substring of at
    least 20 chars must overlap.
    """
    if not excerpt:
        return False
    excerpt = excerpt.strip()
    if not excerpt:
        return False
    haystack = source_text.lower()
    needle = excerpt.lower()
    if len(needle) <= 20:
        return needle in haystack
    return needle[:20] in haystack


def _resolve_fill_slots_template(project_root: Path | str | None) -> "PromptTemplate":
    try:
        return resolve("fill_slots", project_root=project_root)
    except (PromptNotFoundError, PromptParseError) as e:
        raise RuntimeError(
            f"V7 fill_slots prompt is not available: {e}. "
            f"Check that prompts/builtin/fill_slots.toml is installed."
        ) from e


# ---------------------------------------------------------------------------
# Task 18 (Stage 5B): re-export the deterministic page synthesis API.
#
# ``fill_slots`` / ``ConceptPage`` / ``Slot`` / ``SlotEvidence`` /
# ``CONCEPT_SLOTS`` are intentionally untouched — they remain the Stage 7
# wiki_writer contract until Tasks 19-22 land. The v2 entry point
# (``fill_slots_v2``) lives in ``page_synthesizer.py`` and is re-exported
# here so callers can ``from src.pipeline.v7_extract.slot_filler import
# fill_slots_v2`` without a second import path.
# ---------------------------------------------------------------------------

from .page_synthesizer import (  # noqa: E402  (re-export at module bottom)
    FillResult,
    FillStatus,
    fill_slots_v2,
    map_fill_to_extraction,
    synthesize_slot,
)
