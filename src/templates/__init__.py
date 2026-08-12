"""Public facade for knowledge-base scenario templates."""

from .loader import (
    Template,
    apply_template,
    create,
    delete,
    list_templates,
    load,
    update_metadata,
    update_content,
)

__all__ = [
    "Template", "apply_template", "create", "delete", "list_templates",
    "load", "update_metadata", "update_content",
]
