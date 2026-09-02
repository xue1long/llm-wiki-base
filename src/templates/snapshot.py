"""Compatibility import for template snapshot operations."""
from .contract import TemplateSnapshot, load_template_snapshot, persist_template_snapshot

__all__ = ["TemplateSnapshot", "load_template_snapshot", "persist_template_snapshot"]
