"""Claim + Evidence data model for the Knowledge OS."""

import time
from dataclasses import dataclass, field
from enum import Enum


class ClaimType(str, Enum):
    """Classification of a claim's nature."""

    FACT = "fact"
    OPINION = "opinion"
    HYPOTHESIS = "hypothesis"
    WARNING = "warning"


class ClaimStatus(str, Enum):
    """Verification status of a claim."""

    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"


@dataclass
class Evidence:
    """A piece of evidence supporting or refuting a claim."""

    source_path: str
    page: int | None = None
    quote: str = ""
    added_at: int = 0

    def __post_init__(self):
        if self.added_at == 0:
            self.added_at = int(time.time() * 1000)


@dataclass
class Claim:
    """A claim — an assertion backed by evidence, sourced from knowledge objects."""

    id: str
    statement: str
    type: ClaimType = ClaimType.FACT
    confidence: float = 0.0
    evidence: list[Evidence] = field(default_factory=list)
    status: ClaimStatus = ClaimStatus.PENDING
    source_objects: list[str] = field(default_factory=list)
    created_at: int = 0
    updated_at: int = 0

    def __post_init__(self):
        now = int(time.time() * 1000)
        if self.created_at == 0:
            self.created_at = now
        if self.updated_at == 0:
            self.updated_at = now
