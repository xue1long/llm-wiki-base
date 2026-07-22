"""Wiki page model compatibility module.

``WikiPage`` currently lives alongside the shared enums and task types in
``core.types``.  This focused module provides the page-model layer without
introducing a second implementation or changing the model's import identity.
"""

from .types import WikiPage

__all__ = ["WikiPage"]
