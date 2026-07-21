"""Schema base — forward-compatible Pydantic models.

All schemas in ruflo-kb inherit from ForwardCompatModel. Unknown fields
are preserved (not rejected), enabling forward-compatible schema evolution.
"""
from typing import Any

from pydantic import BaseModel, ConfigDict


class ForwardCompatModel(BaseModel):
    """Pydantic model with extra='allow' (unknown fields preserved)."""
    model_config = ConfigDict(extra="allow")

    def to_yaml_compatible(self) -> dict[str, Any]:
        """Convert to dict suitable for YAML serialization."""
        return self.model_dump(exclude_none=False)

    @classmethod
    def from_yaml_compatible(cls, data: dict[str, Any]) -> "ForwardCompatModel":
        """Parse from dict (e.g., loaded from YAML frontmatter)."""
        return cls.model_validate(data)
