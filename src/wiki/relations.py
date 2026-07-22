"""Typed relations between wiki pages (bidirectional)."""
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Optional


class RelationType(str, Enum):
    IS_PART_OF = "is_part_of"
    CONTAINS = "contains"
    REFERENCES = "references"
    REFERENCED_BY = "referenced_by"
    CAUSES = "causes"
    CAUSED_BY = "caused_by"
    CONTRADICTS = "contradicts"     # symmetric
    SUPPORTS = "supports"
    SUPPORTED_BY = "supported_by"
    SUPERSEDES = "supersedes"
    SUPERSEDED_BY = "superseded_by"
    DEPENDS_ON = "depends_on"
    REQUIRED_BY = "required_by"
    ANALOGOUS_TO = "analogous_to"   # symmetric
    OPPOSITE_OF = "opposite_of"     # symmetric
    DERIVED_FROM = "derived_from"
    DERIVES = "derives"


# Inverse relation table
INVERSE_RELATIONS = {
    "is_part_of": "contains",
    "contains": "is_part_of",
    "references": "referenced_by",
    "referenced_by": "references",
    "causes": "caused_by",
    "caused_by": "causes",
    "contradicts": "contradicts",       # symmetric
    "supports": "supported_by",
    "supported_by": "supports",
    "supersedes": "superseded_by",
    "superseded_by": "supersedes",
    "depends_on": "required_by",
    "required_by": "depends_on",
    "analogous_to": "analogous_to",     # symmetric
    "opposite_of": "opposite_of",       # symmetric
    "derived_from": "derives",
    "derives": "derived_from",
}

USER_TYPE_PREFIX = "x-"


@dataclass
class Relation:
    target_id: str
    type: str                # RelationType.value or f"x-{name}"
    weight: float = 1.0
    context: str = ""

    def to_dict(self) -> dict:
        return {"target": self.target_id, "type": self.type,
                "weight": round(self.weight, 2), "context": self.context}

    @classmethod
    def from_dict(cls, d: dict) -> "Relation":
        return cls(
            target_id=d["target"], type=d["type"],
            weight=d.get("weight", 1.0), context=d.get("context", ""),
        )

    def inverse(self) -> Optional["Relation"]:
        inv_type = INVERSE_RELATIONS.get(self.type)
        if inv_type is None:
            return None
        return Relation(target_id="<this_page_id>", type=inv_type, weight=self.weight, context=self.context)