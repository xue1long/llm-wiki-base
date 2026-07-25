"""Judgment types — 6-dimension quality scores + verdict."""
from dataclasses import asdict, dataclass, field
from typing import Literal


Verdict = Literal["pass", "reject"]   # MVP: only 2 tiers


@dataclass
class JudgmentScores:
    source_type_appropriateness: float
    factuality: float
    completeness: float
    clarity: float
    readability: float
    searchability: float

    @classmethod
    def from_dict(cls, d: dict) -> "JudgmentScores":
        return cls(
            source_type_appropriateness=float(d["source_type_appropriateness"]),
            factuality=float(d["factuality"]),
            completeness=float(d["completeness"]),
            clarity=float(d["clarity"]),
            readability=float(d["readability"]),
            searchability=float(d["searchability"]),
        )


@dataclass
class Judgment:
    page_id: str
    page_type: str
    scores: JudgmentScores
    total_score: float
    verdict: Verdict
    issues: list = field(default_factory=list)
    improvement_suggestions: str = ""
    judged_at: int = 0
    llm_call_count: int = 1

    def to_dict(self) -> dict:
        return {
            "page_id": self.page_id,
            "page_type": self.page_type,
            "scores": asdict(self.scores),
            "total_score": self.total_score,
            "verdict": self.verdict,
            "issues": self.issues,
            "improvement_suggestions": self.improvement_suggestions,
            "judged_at": self.judged_at,
            "llm_call_count": self.llm_call_count,
        }


@dataclass
class BatchJudgmentResult:
    pages: dict[str, Judgment]   # slug → Judgment
    pages_passed: list
    pages_rejected: list
    pages_quarantined: list


@dataclass
class QualitySettings:
    # Default OFF (P1 fix): the inline judge in run_ingest costs 5-15s
    # per ingest. Opt-in via the per-project settings file or a future
    # RUFLO_QUALITY_ENABLED env var. Aligns with Plan 19/20/21 audit
    # principle that quality gates must not silently change the main
    # flow's behaviour.
    enabled: bool = False
    weights: dict = field(default_factory=lambda: {
        "source_type_appropriateness": 0.15,
        "factuality": 0.30,
        "completeness": 0.20,
        "clarity": 0.15,
        "readability": 0.10,
        "searchability": 0.10,
    })
    threshold_pass: float = 0.7
    max_retries: int = 1


def compute_total(scores: JudgmentScores, weights: dict) -> float:
    total = 0.0
    for dim, w in weights.items():
        v = getattr(scores, dim)
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"Score out of range: {dim}={v}")
        total += w * v
    return round(total, 4)


def verdict_for(total: float, settings: QualitySettings) -> Verdict:
    return "pass" if total >= settings.threshold_pass else "reject"
