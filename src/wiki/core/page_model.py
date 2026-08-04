"""Wiki page model compatibility module.

``WikiPage`` currently lives alongside the shared enums and task types in
``core.types``.  This focused module provides the page-model layer without
introducing a second implementation or changing the model's import identity.

.. deprecated::
    Import from `src.wiki.core.types` instead of `src.wiki.core.page_model`.
    This module is kept for backwards compatibility only.
"""
import warnings

warnings.warn(
    "Importing from 'src.wiki.core.page_model' is deprecated. "
    "Use 'from src.wiki.core.types import WikiPage' instead.",
    DeprecationWarning,
    stacklevel=2
)

from .types import WikiPage

__all__ = ["WikiPage"]
