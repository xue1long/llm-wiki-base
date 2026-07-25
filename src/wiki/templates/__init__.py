"""Wiki page templates — bundled defaults + project/user overrides.

Public API:
    Template, resolve, list_available
"""
from .resolver import Template, resolve, list_available

__all__ = ["Template", "resolve", "list_available"]
