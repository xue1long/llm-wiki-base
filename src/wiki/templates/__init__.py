"""Wiki page templates — bundled defaults + project/user overrides.

Public API:
    Template, resolve, list_resolved

`Template` is the resolved template (with includes expanded, slot markers
preserved). `resolve()` loads the highest-priority template for a given
PageType. `list_resolved()` returns all 4 PageType templates in
priority order.

See docs/superpowers/plans/2026-07-25-wiki-page-templates.md for the
design.
"""
from .types import Template
from .resolver import resolve, list_resolved

__all__ = ["Template", "resolve", "list_resolved"]
