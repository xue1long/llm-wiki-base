from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


ScreeningDecision = Literal["accept", "skip", "review"]
ScreeningMethod = Literal["rule", "llm", "fallback"]


@dataclass(frozen=True)
class ScreeningResult:
    decision: ScreeningDecision
    content_type: str = "unknown"
    confidence: float = 0.0
    reason: str = ""
    method: ScreeningMethod = "rule"
    metadata: dict[str, object] = field(default_factory=dict)
