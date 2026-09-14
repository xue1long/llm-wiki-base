"""Stage 4 topic clustering for the V7 extract pipeline.

The stage deliberately keeps the output small and deterministic.  An LLM can
provide topic assignments when available, while the keyword fallback keeps
offline runs useful and prevents one concept page per source fragment.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(eq=True)
class Topic:
    """A bounded topic cluster and the source item ids assigned to it."""

    id: str
    title: str
    item_ids: list[str]


_TOPIC_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("冲突升级", ("冲突", "对手", "矛盾", "对抗", "危机")),
    ("角色动机", ("动机", "选择", "欲望", "角色", "人物")),
    ("世界观设定", ("世界观", "设定", "规则", "地图", "背景")),
    ("节奏转折", ("节奏", "转折", "反转", "悬念", "推进")),
    ("聊天主题", ("聊天", "问答", "提问", "回答")),
)


def cluster_topics(
    items: Iterable[Any],
    *,
    llm: Any = None,
    min_topics: int = 3,
    max_topics: int = 5,
) -> list[Topic]:
    """Cluster source items into between ``min_topics`` and ``max_topics``.

    ``items`` may contain mappings with ``id``/``text`` keys or objects with
    matching attributes.  LLM responses must be JSON with a ``topics`` list;
    malformed responses are ignored and the deterministic fallback is used.
    """
    normalized = [_item_parts(item, index) for index, item in enumerate(items)]
    if not normalized:
        return []
    if llm is not None:
        result = _cluster_with_llm(normalized, llm, min_topics, max_topics)
        if result:
            return result
    return _cluster_heuristic(normalized, min_topics, max_topics)


def _cluster_with_llm(
    items: list[tuple[str, str]], llm: Any, min_topics: int, max_topics: int
) -> list[Topic]:
    prompt = "\n".join(f"{item_id}: {text}" for item_id, text in items)
    try:
        response = llm.complete(
            prompt_kind="cluster",
            user_prompt=(
                "将素材按主主题聚类。输出 JSON："
                '{"topics":[{"id":"stable-slug","title":"主题",'
                '"item_ids":["..."]}]}。主题数量控制在 '
                f"{min_topics}-{max_topics}。素材：\n{prompt}"
            ),
            system_prompt="只输出 JSON，不要解释。",
            max_tokens=4096,
            temperature=0.0,
        )
        if inspect.isawaitable(response):
            response = asyncio.run(response)
        payload = json.loads(_strip_json_fence(str(response)))
        raw_topics = payload.get("topics", [])
        if not isinstance(raw_topics, list):
            return []
        item_ids = {item_id for item_id, _ in items}
        topics: list[Topic] = []
        assigned: set[str] = set()
        for index, raw in enumerate(raw_topics):
            if not isinstance(raw, dict):
                continue
            ids = [str(value) for value in raw.get("item_ids", []) if str(value) in item_ids]
            ids = list(dict.fromkeys(ids))
            if not ids:
                continue
            topic_id = str(raw.get("id") or f"topic-{index + 1}")
            title = str(raw.get("title") or topic_id)
            topics.append(Topic(topic_id, title, ids))
            assigned.update(ids)
        missing = [(item_id, text) for item_id, text in items if item_id not in assigned]
        if missing:
            fallback = _cluster_heuristic(missing, 1, 1)[0]
            topics.append(Topic(fallback.id, fallback.title, fallback.item_ids))
        # Very short inputs do not need artificial empty/split topics.  The
        # bounded minimum is enforced for genuinely batch-sized documents.
        effective_min = min_topics if len(items) >= 10 else 1
        if effective_min <= len(topics) <= max_topics:
            return topics
    except (TypeError, ValueError, KeyError, RuntimeError):
        return []
    return []


def _cluster_heuristic(
    items: list[tuple[str, str]], min_topics: int, max_topics: int
) -> list[Topic]:
    buckets: dict[str, list[str]] = {}
    for item_id, text in items:
        title = _topic_title(text)
        buckets.setdefault(title, []).append(item_id)

    if len(buckets) > max_topics:
        ordered = sorted(buckets.items(), key=lambda pair: (-len(pair[1]), pair[0]))
        kept = ordered[: max_topics - 1]
        remainder = [item_id for _, ids in ordered[max_topics - 1 :] for item_id in ids]
        buckets = dict(kept)
        buckets["其他主题"] = remainder

    if len(buckets) < min_topics and len(items) >= min_topics:
        # Split only large fallback buckets; this gives large list documents
        # a useful bounded shape without fragmenting short documents.
        while len(buckets) < min_topics:
            source_title, ids = max(buckets.items(), key=lambda pair: len(pair[1]))
            if len(ids) < 2:
                break
            midpoint = (len(ids) + 1) // 2
            buckets[source_title] = ids[:midpoint]
            buckets[f"{source_title}（补充）"] = ids[midpoint:]

    return [
        Topic(f"topic-{index + 1}", title, ids)
        for index, (title, ids) in enumerate(buckets.items())
        if ids
    ]


def _item_parts(item: Any, index: int) -> tuple[str, str]:
    if isinstance(item, dict):
        item_id = item.get("id", item.get("item_id", index))
        text = item.get("text", item.get("content", item.get("title", "")))
    else:
        item_id = getattr(item, "id", getattr(item, "item_id", index))
        text = getattr(item, "text", getattr(item, "content", getattr(item, "title", "")))
    return str(item_id), str(text or "")


def _topic_title(text: str) -> str:
    for title, hints in _TOPIC_HINTS:
        if any(hint in text for hint in hints):
            return title
    return "综合主题"


def _strip_json_fence(text: str) -> str:
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    return match.group(1) if match else text.strip()
