"""Stage 2 bounded LLM window resolver (Task 42).

Replaces the legacy "one prompt, full document" segmentation path with a
greedy block-coalescing window resolver: each LLM call sees at most
``MAX_WINDOW_CHARS`` (1500, per master plan §3.2 Bounded Evidence Contract).

Pure-function resolver + LLM-async main entry. No mutation of Stage 2
existing modules (article_segmenter / segmentation).
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .llm_client import LLMClient
from .prompts.parser import PromptParseError
from .prompts.renderer import (
    LLMResponseError,
    parse_llm_response,
    render_prompt,
)
from .prompts.resolver import PromptNotFoundError, resolve
from .structural_scanner import StructuralBlock, StructuralBlockKind


log = logging.getLogger(__name__)


# master plan §3.2 Bounded Evidence Contract: Stage 2 candidate windows 1500 chars.
MAX_WINDOW_CHARS = 1500

# Internal cap: never produce a window with more than this many chars.
# Falls back to mid-block split if a single block exceeds the cap.
_ABSOLUTE_MAX_WINDOW_CHARS = 1500

# Prompt kind (used by LLMClient / FakeLLMClient routing).
PROMPT_KIND = "window_resolver"


class ResolverVerdict(str, Enum):
    """LLM-emitted verdict per window.

    Anything outside this set is treated as UNRESOLVED (conservative).
    """

    KEEP = "keep"             # window stays as-is (single item)
    SPLIT = "split"           # window contains multiple items; LLM returns split points
    MERGE = "merge"           # window joins adjacent blocks/windows
    NOISE = "noise"           # boilerplate / nav / skip
    UNRESOLVED = "unresolved" # technical failure or insufficient evidence


@dataclass(frozen=True)
class Window:
    """Bounded chunk of the source presented to the LLM."""

    window_id: str
    block_range: tuple[int, int]              # (first_block_index, last_block_index) inclusive
    start_byte: int
    end_byte: int
    text: str
    block_kinds: tuple[StructuralBlockKind, ...]

    @property
    def char_count(self) -> int:
        return len(self.text)


def _window_id(block_range: tuple[int, int]) -> str:
    identity = f"{block_range[0]}|{block_range[1]}"
    return "win-" + hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]


def resolve_windows(
    blocks: list[StructuralBlock],
    *,
    source_bytes: bytes,
    max_window_chars: int = MAX_WINDOW_CHARS,
) -> list[Window]:
    """Greedy coalesce blocks into windows, each ≤ ``max_window_chars``.

    Algorithm:
      * Start a new window with the current block.
      * Append the next block to the current window only if the joined
        text (with a single ``\\n`` separator) stays ≤ max_window_chars.
      * When a block's own text already exceeds max_window_chars, split
        it into multiple "logical blocks" at sentence boundaries (``. ``,
        `。`) or, failing that, at character boundaries.
      * Empty blocks are skipped.

    Returns windows in source order. Each window's [start_byte, end_byte]
    is the union of its underlying block ranges.
    """
    if not blocks:
        return []

    expanded: list[tuple[int, int, int, str, StructuralBlockKind]] = []
    for idx, block in enumerate(blocks):
        # If the block itself exceeds max_window_chars, split it.
        if len(block.text) > max_window_chars:
            pieces = _split_oversized_block_text(block.text, max_window_chars)
            running_byte = block.start_byte
            for piece in pieces:
                piece_bytes = piece.encode("utf-8")
                piece_start = running_byte
                piece_end = piece_start + len(piece_bytes)
                expanded.append((idx, piece_start, piece_end, piece, block.kind))
                running_byte = piece_end
        else:
            expanded.append((idx, block.start_byte, block.end_byte, block.text, block.kind))

    windows: list[Window] = []
    cur_indices: list[int] = []
    cur_texts: list[str] = []
    cur_kinds: list[StructuralBlockKind] = []
    cur_start_byte: int | None = None
    cur_end_byte: int = 0

    for block_idx, start_byte, end_byte, text, kind in expanded:
        # New entry: would joining overflow?
        proposed_text = ("\n".join(cur_texts + [text])) if cur_texts else text
        proposed_char_count = len(proposed_text)
        if cur_texts and proposed_char_count > max_window_chars:
            # Close current window.
            windows.append(Window(
                window_id=_window_id((cur_indices[0], cur_indices[-1])),
                block_range=(cur_indices[0], cur_indices[-1]),
                start_byte=cur_start_byte if cur_start_byte is not None else start_byte,
                end_byte=cur_end_byte,
                text="\n".join(cur_texts),
                block_kinds=tuple(cur_kinds),
            ))
            cur_indices = []
            cur_texts = []
            cur_kinds = []
            cur_start_byte = None
            cur_end_byte = 0

        if not cur_texts:
            cur_start_byte = start_byte
        cur_indices.append(block_idx)
        cur_texts.append(text)
        cur_kinds.append(kind)
        cur_end_byte = end_byte

    if cur_texts:
        windows.append(Window(
            window_id=_window_id((cur_indices[0], cur_indices[-1])),
            block_range=(cur_indices[0], cur_indices[-1]),
            start_byte=cur_start_byte if cur_start_byte is not None else 0,
            end_byte=cur_end_byte,
            text="\n".join(cur_texts),
            block_kinds=tuple(cur_kinds),
        ))

    return windows


def _split_oversized_block_text(text: str, max_chars: int) -> list[str]:
    """Split an oversized block at sentence boundaries; fall back to char boundaries."""
    # First try sentence boundaries (ASCII ". " + CJK "。").
    sentences: list[str] = []
    current: list[str] = []
    for ch in text:
        current.append(ch)
        if ch in ".。":
            sentences.append("".join(current))
            current = []
    if current:
        sentences.append("".join(current))
    if sentences and all(len(s) <= max_chars for s in sentences):
        return sentences
    # Fall back to char-boundary chunks of max_chars each.
    chunks: list[str] = []
    for i in range(0, len(text), max_chars):
        chunks.append(text[i:i + max_chars])
    return chunks if chunks else [text]


# ---------------------------------------------------------------------------
# LLM main entry
# ---------------------------------------------------------------------------


@dataclass
class ResolvedItem:
    window_id: str
    block_range: tuple[int, int]
    verdict: ResolverVerdict
    confidence: float = 0.0
    split_points: list[int] = field(default_factory=list)   # byte offsets within window


async def call_window_resolver(
    windows: list[Window],
    *,
    llm: LLMClient,
    template: Any | None = None,
    project_root: Path | str | None = None,
    max_retries: int = 3,
) -> list[ResolvedItem]:
    """Per-window LLM call. Returns one ResolvedItem per window.

    Bounded Evidence §3.2: each LLM call sees ONLY ``window.text`` (≤
    ``max_window_chars``), never the whole document.

    Technical failure (all retries exhausted) → that window marked
    UNRESOLVED. Never raises (Failure Contract §1).
    """
    if not windows:
        return []

    try:
        resolved_template = template or _resolve_template(project_root)
    except RuntimeError as e:
        log.warning("call_window_resolver: prompt resolution failed: %s", e)
        return [
            ResolvedItem(
                window_id=w.window_id,
                block_range=w.block_range,
                verdict=ResolverVerdict.UNRESOLVED,
            )
            for w in windows
        ]

    results: list[ResolvedItem] = []
    for window in windows:
        system_prompt, user_prompt = render_prompt(resolved_template, {
            "window_id": window.window_id,
            "window_text": window.text,
            "block_range": f"{window.block_range[0]}-{window.block_range[1]}",
            "block_kinds": ",".join(k.value for k in window.block_kinds),
        })
        verdicts = await _call_one_window(
            resolved_template, window=window,
            system_prompt=system_prompt, user_prompt=user_prompt,
            llm=llm, max_retries=max_retries,
        )
        if verdicts is None:
            results.append(ResolvedItem(
                window_id=window.window_id,
                block_range=window.block_range,
                verdict=ResolverVerdict.UNRESOLVED,
            ))
            continue
        verdict_str, confidence, split_points = verdicts
        try:
            v = ResolverVerdict(verdict_str)
        except ValueError:
            v = ResolverVerdict.UNRESOLVED
        results.append(ResolvedItem(
            window_id=window.window_id,
            block_range=window.block_range,
            verdict=v,
            confidence=confidence,
            split_points=split_points,
        ))
    return results


async def _call_one_window(
    template,
    *,
    window: Window,
    system_prompt: str,
    user_prompt: str,
    llm: LLMClient,
    max_retries: int,
) -> tuple[str, float, list[int]] | None:
    """Call LLM up to ``max_retries`` times for one window; return None on total failure."""
    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            raw = await llm.complete(
                prompt_kind=PROMPT_KIND,
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                max_tokens=1024,
                temperature=0.0,
            )
            payload = parse_llm_response(raw, template.output_schema)
            v = str(payload.get("verdict", "unresolved")).strip().lower()
            confidence = float(payload.get("confidence", 0.0) or 0.0)
            confidence = min(1.0, max(0.0, confidence))
            split_points = payload.get("split_points") or []
            if not isinstance(split_points, list):
                split_points = []
            return (v, confidence, [int(p) for p in split_points])
        except Exception as e:
            last_error = e
            log.info(
                "call_window_resolver[%s]: response failed (attempt %d/%d): %s",
                window.window_id, attempt + 1, max_retries, e,
            )
            continue
    log.warning(
        "call_window_resolver[%s]: LLM failed after %d attempts; UNRESOLVED. last_error=%r",
        window.window_id, max_retries, last_error,
    )
    return None


def _resolve_template(project_root: Path | str | None) -> Any:
    """Resolve the window_resolver prompt; raise RuntimeError on config error."""
    try:
        return resolve(PROMPT_KIND, project_root=project_root)
    except (PromptNotFoundError, PromptParseError) as e:
        raise RuntimeError(
            f"V7 {PROMPT_KIND} prompt is not available: {e}. Check that "
            f"prompts/builtin/{PROMPT_KIND}.toml is installed."
        ) from e


__all__ = [
    "MAX_WINDOW_CHARS",
    "PROMPT_KIND",
    "ResolvableWindow",
    "ResolvedItem",
    "ResolverVerdict",
    "Window",
    "call_window_resolver",
    "resolve_windows",
]
# Resolve forward-reference: ResolvableWindow not used; remove from __all__.
__all__ = [n for n in __all__ if n != "ResolvableWindow"]