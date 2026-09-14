"""Stage 4 topic clustering for the V7 extract pipeline.

The stage deliberately keeps the output small and deterministic. An LLM can
provide topic assignments when available, while the keyword fallback keeps
offline runs useful and prevents one concept page per source fragment.

Boundary of responsibility (RFC v6 §Stage 4):

* The script side (extract_pilot / extract_full) preserves the source's
  heading and item boundaries. Items are passed in with stable ids.
* The LLM decides topic boundaries, topic titles, and semantic grouping
  when it is available.
* This module enforces: 100 % item coverage, the 3–5 topic bound for
  batch-sized inputs, no single-document fragmentation, and "综合主题"
  is reserved as a low-confidence heuristic fallback only.

Title priorities (highest first):

1. LLM-supplied semantic title.
2. The first heading / section title found in the topic's source text.
3. The source document's title.
4. ``"综合主题"`` only as a last-resort heuristic fallback.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(eq=True)
class Topic:
    """A bounded topic cluster and the source item ids assigned to it."""

    id: str
    title: str
    item_ids: list[str]


_FALLBACK_TOPIC_TITLE = "综合主题"


def cluster_topics(
    items: Iterable[Any],
    *,
    llm: Any = None,
    min_topics: int = 3,
    max_topics: int = 5,
) -> list[Topic]:
    """Cluster source items into between ``min_topics`` and ``max_topics``.

    ``items`` may contain mappings with ``id``/``text`` keys or objects with
    matching attributes. LLM responses must be JSON with a ``topics`` list;
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
    prompt = "\n".join(f"{item_id}: {text[:200]}" for item_id, text in items)
    try:
        response = llm.complete(
            prompt_kind="cluster",
            user_prompt=(
                "将素材按主主题聚类。优先使用素材中已有的章节标题或文档标题。"
                "不要把单一文档强行拆成多个'综合主题'。输出 JSON："
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
            # Disallow '综合主题' as a successful LLM title — keep it for
            # the heuristic fallback only.
            if title.strip() == _FALLBACK_TOPIC_TITLE:
                title = topic_id
            topics.append(Topic(topic_id, title, ids))
            assigned.update(ids)
        missing = [(item_id, text) for item_id, text in items if item_id not in assigned]
        if missing:
            fallback = _cluster_heuristic(missing, 1, 1)[0]
            topics.append(Topic(fallback.id, fallback.title, fallback.item_ids))
        # Very short inputs do not need artificial empty/split topics. The
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
    """Deterministic fallback.

    Strategy
    --------
    1. Group by the *first heading* found in each item's text (or the
       document title when no heading exists). This produces natural
       per-section clusters and avoids the "综合主题" explosion.
    2. If grouping produces more than ``max_topics`` buckets, keep the
       largest ``max_topics - 1`` buckets and merge the rest under
       "其他主题" (the legitimate "综合主题" low-confidence fallback).
    3. If grouping produces fewer than ``min_topics`` buckets AND the
       total item count is large enough to warrant splitting, split the
       largest bucket into two (with a "（补充）" suffix). This gives
       list-style documents a useful bounded shape without fragmenting
       short documents.
    """
    buckets: dict[str, list[str]] = {}
    for item_id, text in items:
        title = _topic_title(text)
        buckets.setdefault(title, []).append(item_id)

    if len(buckets) > max_topics:
        ordered = sorted(buckets.items(), key=lambda pair: (-len(pair[1]), pair[0]))
        kept = ordered[: max_topics - 1]
        remainder = [item_id for _, ids in ordered[max_topics - 1 :] for item_id in ids]
        buckets = dict(kept)
        if remainder:
            buckets[_FALLBACK_TOPIC_TITLE] = remainder

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


# Pre-compiled heading finders. Heading-like lines start with 1–3 `#` chars
# or with a Chinese numbered chapter marker like "第一章" / "第一节".
_HEADING_RE = re.compile(r"(?m)^#{1,3}\s+(.+?)\s*$")
_CHAPTER_RE = re.compile(r"(?m)^(第[一二三四五六七八九十百\d]+[章节篇])\s*([^:\n]*?)(?:[:：]|\n|$)")
# Trailing-number / trailing-ordinal normaliser. Strips "：桥段 10" /
# ": item 12" / "（续）" so that items belonging to the same conceptual
# bucket share a normalised title and cluster together.
_TRAILING_NUMBER_RE = re.compile(
    r"(?:"
    r"[:：]\s*(?:桥段|条目|节|例|案例|片段|子项)\s*\d+"
    r"|[:：]\s*\d+"
    r"|（续）|\(续\)|（续集）|\(续集\)"
    r")\s*$"
)


def _normalise_heading(raw: str) -> str:
    """Strip trailing ordinals / continuations so headings like
    "冲突升级：桥段 10" and "冲突升级：桥段 11" bucket together."""
    title = raw.strip()
    title = _TRAILING_NUMBER_RE.sub("", title).strip()
    return title or raw.strip()


def _topic_title(text: str) -> str:
    """Pick a topic title from item text.

    Priority:
        1. First Markdown heading in the item, normalised.
        2. First Chinese chapter / section marker.
        3. First non-empty line, stripped.
        4. ``"综合主题"`` only when none of the above is available.

    The keyword-based hints used by the previous implementation caused
    systematic mis-titling (e.g. "冲突设计" → "冲突升级"). This version
    uses the source's own headings so titles stay faithful to the
    source material.
    """
    if not text:
        return _FALLBACK_TOPIC_TITLE
    heading = _HEADING_RE.search(text)
    if heading:
        title = _normalise_heading(heading.group(1))
        if title:
            return title
    chapter = _CHAPTER_RE.search(text)
    if chapter:
        marker = chapter.group(1).strip()
        body = chapter.group(2).strip()
        title = f"{marker} {body}".strip() if body else marker
        if title:
            return title
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped[:60]
    return _FALLBACK_TOPIC_TITLE


def _strip_json_fence(text: str) -> str:
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    return match.group(1) if match else text.strip()


# Exposed for tests / diagnostics — keeps a tiny view of how items are
# bucketed without changing the public function signatures.
def _topic_distribution(items: Iterable[Any]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for item in items:
        _, text = _item_parts(item, 0)
        counter[_topic_title(text)] += 1
    return counter
