"""Wiki page templates — bundled defaults + project/user overrides.

Public API:
    Template, resolve, list_resolved,
    required_slot_names, render_body, SlotFillStatus, compute_slot_fill_status

`Template` is the resolved template (with includes expanded, slot markers
preserved). `resolve()` loads the highest-priority template for a given
PageType. `list_resolved()` returns all 4 PageType templates in
priority order.

`required_slot_names(template)` returns the names of slots that must be
filled for a rendered body to be considered structurally complete.
`render_body(template_body, slots, page_type)` returns a wiki page body
with slot markers replaced by content. `compute_slot_fill_status` returns
a `SlotFillStatus` audit of how a slot dict maps against a required-slot
list; useful for the Generator's retry loop.

See docs/superpowers/plans/2026-07-25-wiki-page-templates.md for the
template design, and docs/superpowers/plans/2026-07-26-wiki-schema-v23.md
for the v2.3 schema enforcement work.
"""
from .types import Template
from .resolver import resolve, list_resolved
from .parser import required_slot_names
from .renderer import render_body, SlotFillStatus, compute_slot_fill_status

__all__ = [
    "Template",
    "resolve",
    "list_resolved",
    "required_slot_names",
    "render_body",
    "SlotFillStatus",
    "compute_slot_fill_status",
]
