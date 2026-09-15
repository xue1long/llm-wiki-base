"""Prompt renderer + LLM response parser — mirrors src/wiki/templates/renderer.py.

Three responsibilities:

  * ``render_prompt(template, slot_values)``
      Substitute ``{slot_name}`` placeholders in the user-template.
      Missing required slots → ``PromptSlotMissingError``.
      Stray slots (in ``slot_values`` but not declared) are silently
      ignored — matches ``templates/renderer.compute_slot_fill_status``
      semantics.

  * ``compute_prompt_fill_status(template, available)``
      Audit helper: returns ``{missing, extra}`` for logging / metrics.

  * ``parse_llm_response(raw, schema)``
      Strip ```json fences, ``json.loads`` the body, validate against
      ``output_schema`` (required / enum / range). Raises
      ``LLMResponseError`` on any failure so the caller's retry loop
      (D2) can decide whether to ask the LLM to fix the response.

D9: schema validation is part of parse, not a separate step. This
prevents the "parse OK but schema invalid" hole where downstream code
trusts a malformed payload.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .ast import PromptTemplate


_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class PromptSlotMissingError(Exception):
    """Raised when a required slot has no value supplied at render time."""


class LLMResponseError(Exception):
    """Raised when the LLM response fails JSON parsing or schema validation."""


def render_prompt(
    template: PromptTemplate,
    slot_values: dict[str, Any],
) -> tuple[str, str]:
    """Substitute ``{slot_name}`` placeholders.

    Returns:
        (system_prompt, user_prompt)

    Raises:
        PromptSlotMissingError: when a required slot has no value.
    """
    # Discover required slots by inspecting the user template string
    # for {slot_name} tokens — this avoids coupling to PromptTemplate
    # metadata. PromptTemplate doesn't carry slot metadata directly.
    required = _required_slot_names(template.user_template)
    missing = [name for name in required if name not in slot_values]
    if missing:
        raise PromptSlotMissingError(
            f"Required slot(s) not provided: {missing}"
        )

    user = template.user_template
    for name, value in slot_values.items():
        user = user.replace("{" + name + "}", str(value))
    return template.system_section, user


def compute_prompt_fill_status(
    template: PromptTemplate,
    available: dict[str, Any],
) -> dict[str, list[str]]:
    """Audit helper — mirror of templates/renderer.compute_slot_fill_status."""
    required = _required_slot_names(template.user_template)
    declared = set(_all_slot_names(template.user_template))
    return {
        "missing": sorted(name for name in required if name not in available),
        "extra": sorted(name for name in available if name not in declared),
    }


def parse_llm_response(raw: str, schema: dict | None) -> dict[str, Any]:
    """Strip fences, parse JSON, validate against ``output_schema``.

    D9: validation includes enum whitelist + numeric range — same
    rules the parser enforces on the prompt file itself, so the LLM
    cannot smuggle in values that would bypass Stage-5 evidence checks.

    Raises:
        LLMResponseError: on any parse or schema failure.
    """
    if raw is None:
        raise LLMResponseError("LLM returned None")

    text = raw.strip()
    if not text:
        raise LLMResponseError("LLM returned empty string")

    # Strip ```json ... ``` fences (model often wraps JSON)
    if text.startswith("```"):
        text = _JSON_FENCE_RE.sub("", text).strip()
        if text.startswith("```"):  # nested fence, e.g. ```json\n```json\n{...}\n```
            text = _JSON_FENCE_RE.sub("", text).strip()

    try:
        payload = json.loads(text)
    except (TypeError, ValueError) as e:
        raise LLMResponseError(f"LLM response is not valid JSON: {e}") from e

    if not isinstance(payload, dict):
        raise LLMResponseError(
            f"LLM response top-level is {type(payload).__name__}, expected object"
        )

    if schema is None:
        return payload

    # Required keys
    for key in schema.get("required", []):
        if key not in payload:
            raise LLMResponseError(f"Missing required key: {key!r}")

    # Enum membership
    enum_block = schema.get("enum") or {}
    if isinstance(enum_block, dict):
        for key, allowed in enum_block.items():
            if key in payload and payload[key] not in allowed:
                raise LLMResponseError(
                    f"Key {key!r}={payload[key]!r} not in allowed enum: {allowed}"
                )

    # Numeric range
    range_block = schema.get("range") or {}
    if isinstance(range_block, dict):
        for key, bounds in range_block.items():
            if key not in payload:
                continue
            value = payload[key]
            if not isinstance(value, (int, float)):
                raise LLMResponseError(
                    f"Key {key!r}={value!r} is not numeric, cannot range-check"
                )
            lo, hi = bounds
            if not (lo <= value <= hi):
                raise LLMResponseError(
                    f"Key {key!r}={value} out of range [{lo}, {hi}]"
                )

    return payload


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_SLOT_TOKEN_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _all_slot_names(template_text: str) -> list[str]:
    """Return all ``{slot_name}`` tokens in the template (deduplicated, in order)."""
    seen: set[str] = set()
    out: list[str] = []
    for match in _SLOT_TOKEN_RE.finditer(template_text):
        name = match.group(1)
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def _required_slot_names(template_text: str) -> list[str]:
    """Required = every slot used in the template (the template is
    authoritative — we don't ship templates with optional placeholders
    yet, so every ``{slot_name}`` is treated as required).

    Future: parse ``[[slot]] required = false`` and skip them here.
    """
    return _all_slot_names(template_text)
