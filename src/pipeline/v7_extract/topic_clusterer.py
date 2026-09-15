"""Stage 4 of the V7 extract pipeline: cluster items into topics.

v3 (plan 2026-09-15): pure-LLM clustering with P4 hard constraint.

P4 says the v7 pipeline must not silently drop items: if the LLM
forgets to assign an item, we route it to a sentinel ``__other__``
topic that the WikiWriter will refuse to write. This guarantees 100%
item coverage at the cost of an extra reviewable topic.

Heuristic fallback ("综合主题" + first-heading bucketization) was
deleted (T2.3). Pure LLM only.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

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


# P4: sentinel topic id for items the LLM forgot to assign. The
# WikiWriter (Stage 7) checks for this id and refuses to write the
# page — its content goes to review_queue instead.
OTHER_TOPIC_ID = "__other__"
OTHER_TOPIC_TITLE = "其他主题"


@dataclass
class Topic:
    """One topic produced by Stage 4."""
    id: str
    title: str
    item_ids: list[str] = field(default_factory=list)


async def cluster_topics(
    items: list[dict],
    *,
    llm: LLMClient,
    project_root: Path | str | None = None,
    min_topics: int = 1,
    max_topics: int = 5,
    max_retries: int = 3,
) -> list[Topic]:
    """Cluster ``items`` into between ``min_topics`` and ``max_topics`` topics.

    Args:
        items: list of dicts with ``id`` and ``text`` keys (Stage 2 output).
        llm: any ``LLMClient``.
        project_root: passed through to ``prompts_resolver.resolve``.
        min_topics: minimum number of topics to emit.
        max_topics: maximum number of topics to emit.

    Returns:
        list of ``Topic`` objects. Always returns — never raises (P2).
        When the LLM fails every retry the result is an empty list.

        P4: if the LLM fails to assign some items, they go into a
        ``__other__`` bucket that ``WikiWriter`` will refuse to write.
    """
    if not items:
        return []

    template = _resolve_cluster_template(project_root)
    items_text = "\n".join(
        f"{item['id']}: {str(item.get('text', ''))[:200]}"
        for item in items
    )
    system_prompt, user_prompt = render_prompt(template, {
        "min_topics": min_topics,
        "max_topics": max_topics,
        "items_text": items_text,
    })

    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            raw = await llm.complete(
                prompt_kind="cluster",
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                max_tokens=4096,
                temperature=0.0,
            )
            payload = parse_llm_response(raw, template.output_schema)
            topics = _payload_to_topics(payload)
            return _enforce_full_coverage(topics, items)  # P4
        except LLMResponseError as e:
            last_error = e
            log.info(
                "cluster_topics: response failed validation "
                "(attempt %d/%d): %s",
                attempt + 1, max_retries, e,
            )
            continue
        except Exception as e:
            last_error = e
            log.warning(
                "cluster_topics: LLM call failed (attempt %d/%d): %s",
                attempt + 1, max_retries, e,
            )
            continue

    log.error(
        "cluster_topics: all %d retries exhausted, returning []. last_error=%r",
        max_retries, last_error,
    )
    # P4: even on total failure, return a __other__ bucket containing
    # ALL items, so they reach review_queue instead of being lost.
    return _enforce_full_coverage([], items)


def _payload_to_topics(payload: dict) -> list[Topic]:
    """Convert validated LLM JSON payload into Topic list.

    Validates that all item_ids are strings (defensive — the schema
    can't enforce this on free-form JSON).
    """
    raw = payload.get("topics", [])
    if not isinstance(raw, list):
        return []
    topics: list[Topic] = []
    seen: set[str] = set()  # avoid duplicate topic ids
    for idx, entry in enumerate(raw):
        if not isinstance(entry, dict):
            continue
        tid = str(entry.get("id") or f"topic-{idx + 1}")
        # If the LLM produces a duplicate id, suffix it
        original_tid = tid
        suffix = 1
        while tid in seen:
            tid = f"{original_tid}-{suffix}"
            suffix += 1
        seen.add(tid)
        title = str(entry.get("title") or tid)
        ids_raw = entry.get("item_ids", [])
        if not isinstance(ids_raw, list):
            ids_raw = []
        item_ids = [str(i) for i in ids_raw if i]
        topics.append(Topic(id=tid, title=title, item_ids=item_ids))
    return topics


def _enforce_full_coverage(topics: list[Topic], items: list[dict]) -> list[Topic]:
    """P4: every item in ``items`` must appear in some topic.

    Items the LLM forgot to assign are bundled into a sentinel
    ``__other__`` topic. The WikiWriter (Stage 7) refuses to write this
    bucket's pages — they go to review_queue instead.
    """
    assigned: set[str] = {iid for t in topics for iid in t.item_ids}
    all_ids: set[str] = {item["id"] for item in items}
    leftover = sorted(all_ids - assigned)
    if not leftover:
        return topics
    # If a __other__ bucket already exists, merge into it
    for t in topics:
        if t.id == OTHER_TOPIC_ID:
            t.item_ids = sorted(set(t.item_ids) | set(leftover))
            return topics
    topics.append(Topic(
        id=OTHER_TOPIC_ID,
        title=OTHER_TOPIC_TITLE,
        item_ids=leftover,
    ))
    return topics


def _resolve_cluster_template(project_root: Path | str | None) -> "PromptTemplate":
    try:
        return resolve("cluster", project_root=project_root)
    except (PromptNotFoundError, PromptParseError) as e:
        raise RuntimeError(
            f"V7 cluster prompt is not available: {e}. "
            f"Check that prompts/builtin/cluster.toml is installed."
        ) from e
