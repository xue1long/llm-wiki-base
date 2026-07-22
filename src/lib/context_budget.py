"""Conservative token estimation + paragraph-boundary chunking."""
from typing import List


# Known model context windows (tokens). Conservative defaults for unknown.
_MODEL_CONTEXT_WINDOWS = {
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-3.5-turbo": 16_385,
    "claude-opus-4-8": 200_000,
    "claude-sonnet-5": 200_000,
    "claude-haiku-4-5": 200_000,
    "qwen2.5:7b": 32_768,
    "qwen2.5:14b": 32_768,
    "llama3.1:8b": 131_072,
    "llama3.1:70b": 131_072,
}

DEFAULT_CONTEXT_WINDOW = 8_192


def get_model_context_window(model: str) -> int:
    """Return the model's context window in tokens.

    Falls back to DEFAULT_CONTEXT_WINDOW (8K) for unknown models —
    a conservative choice that surfaces chunking needs immediately.
    """
    return _MODEL_CONTEXT_WINDOWS.get(model, DEFAULT_CONTEXT_WINDOW)


def estimate_tokens(text: str) -> int:
    """Conservative: 0.5 token per character.

    Conservative over-estimation ensures we don't exceed LLM context window.
    Under-estimation is safe (we just split unnecessarily).
    """
    if not text:
        return 0
    return len(text) // 2


def chunk_by_budget(text: str, max_tokens: int) -> List[str]:
    """Split text by paragraph boundary (\\n\\n) so each chunk fits in max_tokens.

    Falls back to sentence boundary if a single paragraph exceeds max_tokens.
    Falls back to hard split by max_tokens chars if a sentence exceeds.

    Returns list of chunks; empty list if text is empty.
    """
    if not text:
        return []
    if estimate_tokens(text) <= max_tokens:
        return [text]

    paragraphs = text.split("\n\n")
    chunks: List[str] = []
    current: List[str] = []
    current_tokens = 0

    for para in paragraphs:
        para_tokens = estimate_tokens(para)
        if current and current_tokens + para_tokens > max_tokens:
            chunks.append("\n\n".join(current))
            current = [para]
            current_tokens = para_tokens
        else:
            current.append(para)
            current_tokens += para_tokens

    if current:
        chunks.append("\n\n".join(current))

    # If any chunk still exceeds max_tokens (single huge paragraph), hard-split it
    final: List[str] = []
    for c in chunks:
        if estimate_tokens(c) <= max_tokens:
            final.append(c)
        else:
            # Sentence split
            sentences = _split_sentences(c)
            for s in sentences:
                if estimate_tokens(s) <= max_tokens:
                    final.append(s)
                else:
                    # Hard split by chars
                    for i in range(0, len(s), max_tokens * 2):
                        final.append(s[i:i + max_tokens * 2])
    return final


def _split_sentences(text: str) -> List[str]:
    """Naive sentence split: . ! ? 。 ！ ？"""
    import re
    parts = re.split(r"(?<=[.!?。！？])\s+", text)
    return [p for p in parts if p.strip()]
