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
from .contract import TemplateContract, TemplateSnapshot, load_template_snapshot, persist_template_snapshot
from .compiler import compile_project_template

__all__ = [
    "Template", "apply_template", "create", "delete", "list_templates",
    "load", "update_metadata", "update_content", "TemplateContract", "TemplateSnapshot",
    "compile_project_template", "load_template_snapshot", "persist_template_snapshot",
]
