"""Judgment types — 6-dimension quality scores + verdict."""
import os
import random
from dataclasses import asdict, dataclass, field
from typing import Literal


Verdict = Literal["pass", "reject"]   # MVP: only 2 tiers
JudgeMode = Literal["off", "sample", "full"]


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
    """Quality judge configuration.

    mode:
        - ``"off"`` — judge never runs (default)
        - ``"sample"`` — randomly sample ``sample_rate`` of pages + always_judge rules
        - ``"full"`` — judge every page

    always_judge rules (applied in all modes except "off"):
        - ``always_judge_grade_a`` — grade "A" pages always pass through the judge
        - ``always_judge_low_confidence`` — confidence below this threshold triggers
          mandatory judgment (default 0.7)

    Backward compat: setting ``enabled=True`` is equivalent to ``mode="full"``.
    """
    mode: JudgeMode = "off"
    sample_rate: float = 0.2
    always_judge_grade_a: bool = True
    always_judge_low_confidence: float = 0.7
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

    # Backward compat: enabled=True → mode="full"
    enabled: bool = False

    def __post_init__(self):
        # Resolve legacy enabled flag
        if self.enabled and self.mode == "off":
            self.mode = "full"
        # Validate
        if self.mode not in ("off", "sample", "full"):
            raise ValueError(f"Invalid judge mode: {self.mode}")
        if not (0.0 <= self.sample_rate <= 1.0):
            raise ValueError(f"sample_rate must be in [0.0, 1.0], got {self.sample_rate}")

    def is_active(self) -> bool:
        return self.mode != "off"

    def should_judge(self, *, page_grade: str = "B", page_confidence: float | None = None) -> bool:
        """Return True if this page should go through the quality judge.

        Decision order:
        1. mode="off" → False
        2. mode="full" → True
        3. mode="sample" → random sample, unless always_judge rule triggers
        """
        if self.mode == "off":
            return False
        if self.mode == "full":
            return True

        # mode == "sample"
        # always_judge rules override sampling
        if self.always_judge_grade_a and page_grade == "A":
            return True
        if (
            self.always_judge_low_confidence > 0
            and page_confidence is not None
            and page_confidence < self.always_judge_low_confidence
        ):
            return True

        return random.random() < self.sample_rate


def _parse_mode(raw: str | None) -> JudgeMode:
    """Parse mode string, defaulting to 'off'."""
    if raw is None:
        return "off"
    raw = raw.strip().lower()
    if raw in ("off", "sample", "full"):
        return raw  # type: ignore[return-value]
    return "off"


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
