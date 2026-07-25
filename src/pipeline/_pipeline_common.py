"""Shared helpers for the Collector → Analyzer → Generator pipeline.

Currently houses ``parse_llm_json`` — a lenient JSON parser used by both
the Analyzer and Generator steps. Without ``response_format`` enforcement
(MiniMax / DeepSeek / Kimi all reject any ``response_format`` parameter),
the model often wraps its JSON in markdown fences or appends a prose
preamble, so a strict ``json.loads(content)`` is too brittle.
"""
from __future__ import annotations

import json
import re
from typing import Any


_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)


def parse_llm_json(llm_resp: Any) -> dict:
    """Parse ``LLMResponse.content`` (or a raw dict/str) as a JSON object.

    Tries in order:
      1. Strict ``json.loads`` on the trimmed content (the JSON-mode path).
      2. First markdown-fenced JSON block (```json ... ``` or ``` ... ```).
      3. First balanced JSON object or array in the text.

    Raises ``json.JSONDecodeError`` when no JSON object/array can be
    located. Never returns a partial / silently-empty result.
    """
    # Raw dict (legacy mock / unit test): use as-is.
    if isinstance(llm_resp, dict):
        return llm_resp
    # LLMResponse / any object exposing .content
    content = getattr(llm_resp, "content", llm_resp)
    if not isinstance(content, str):
        # Last-ditch: stringify and parse (covers invalid mocks returning bytes/None).
        content = str(content)

    s = content.strip()
    if not s:
        raise json.JSONDecodeError("LLM returned empty content", content, 0)

    # 1. Strict JSON.
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass

    # 2. Markdown-fenced JSON.
    fence = _FENCE_RE.search(s)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass

    # 3. First balanced JSON object / array.
    for opener, closer in (("{", "}"), ("[", "]")):
        idx = s.find(opener)
        if idx == -1:
            continue
        depth = 0
        for i in range(idx, len(s)):
            ch = s[i]
            if ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    candidate = s[idx : i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break

    raise json.JSONDecodeError(
        f"no JSON object/array found in LLM response ({len(content)} chars)",
        content, 0,
    )