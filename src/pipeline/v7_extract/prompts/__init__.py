"""Prompt infrastructure for the V7 extract pipeline.

Mirrors the design of ``src/wiki/templates/``:

    wiki/templates/types.py    ←→    prompts/ast.py
    wiki/templates/parser.py   ←→    prompts/parser.py
    wiki/templates/renderer.py ←→    prompts/renderer.py
    wiki/templates/resolver.py ←→    prompts/resolver.py
    wiki/templates/bundled/    ←→    prompts/builtin/

Public API:

    PromptAST        -- parsed structure of a single prompt file
    PromptTemplate   -- resolved (with [system] / [user] split) ready to render
    PromptSection    -- one logical chunk (system / user / ...)
    PromptSlot       -- one {slot_name} placeholder
    PromptSource     -- "project" | "user" | "bundled"

Three-layer override (D1):
    project > user > bundled, resolved at runtime on every call (D6 hot-reload).
"""
from .ast import (
    PromptAST,
    PromptSection,
    PromptSlot,
    PromptSource,
    PromptTemplate,
)

__all__ = [
    "PromptAST",
    "PromptSection",
    "PromptSlot",
    "PromptSource",
    "PromptTemplate",
]
