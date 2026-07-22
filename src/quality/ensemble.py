"""Multi-judge ensemble voting for quality gate v2.1."""
import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from ..llm.provider_factory import create_llm_provider
from ..llm.registry import ProviderRegistry
from .types import JudgmentScores, QualitySettings, compute_total, verdict_for
from .judge import JUDGE_PROMPT


_logger = logging.getLogger(__name__)


@dataclass
class JudgeVote:
    judge_name: str
    model: str
    scores: JudgmentScores
    total_score: float
    issues: list = field(default_factory=list)
    improvement_suggestions: str = ""
    llm_call_count: int = 1


@dataclass
class AggregatedJudgment:
    page_id: str
    page_type: str
    votes: list
    aggregated_scores: JudgmentScores
    aggregated_total: float
    verdict: str
    issues: list
    improvement_suggestions: str
    judged_at: int
    llm_call_count: int


class EnsembleJudge:
    """Run several LLM judges in parallel, aggregate via mean + apply veto rules.

    The MVP veto: any judge scoring ``factuality < self.veto_threshold`` triggers
    a hard "reject" verdict (no second chance).
    """

    def __init__(self, settings: QualitySettings, ensemble_judges: Optional[list[str]] = None,
                 primary_provider: str = "openai"):
        self.settings = settings
        self.ensemble_judges = ensemble_judges or []
        self.primary_provider = primary_provider
        # Default veto rules — package-level so tests can mutate.
        self.veto_dimensions = {"factuality"}
        self.veto_threshold = 0.2

    def resolve_judges(self) -> list:
        """Return list of (provider_name, model_override_or_None) tuples."""
        judges = [(self.primary_provider, None)]
        for name in self.ensemble_judges:
            if name != self.primary_provider and name in ProviderRegistry.load():
                judges.append((name, None))
        if len(judges) < 2:
            _logger.warning(
                "[ensemble] only %d judge available; ensemble degraded to single", len(judges)
            )
        return judges

    async def judge_page(self, page_id: str, page_type: str, page_body: str,
                         source_text: str = "") -> AggregatedJudgment:
        """Multi-judge: run N judges in parallel; aggregate via mean + veto."""
        judges = self.resolve_judges()

        async def vote_one(name, model):
            try:
                cfg = ProviderRegistry.get(name)
            except KeyError:
                cfg = None
            provider = create_llm_provider(name, model_override=model)
            prompt = JUDGE_PROMPT.format(
                source_text=(source_text or "")[:3000],
                page_id=page_id, page_type=page_type,
                page_body=(page_body or "")[:2000],
            )
            response = await provider.complete(prompt=prompt)
            raw = response.content if hasattr(response, "content") else response
            if "```" in raw:
                raw = raw.split("```", 2)[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.split("```", 1)[0]
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                data = {}
            scores = _safe_scores(data.get("scores", {}) if isinstance(data, dict) else {})
            total = compute_total(scores, self.settings.weights)
            return JudgeVote(
                judge_name=name,
                model=cfg.default_chat_model if cfg else "",
                scores=scores,
                total_score=total,
                issues=data.get("issues", []) if isinstance(data, dict) else [],
                improvement_suggestions=data.get("improvement_suggestions", "") if isinstance(data, dict) else "",
            )

        votes = await asyncio.gather(*[vote_one(n, m) for n, m in judges])

        # Veto check — any vetod dimension below threshold triggers reject.
        for vote in votes:
            for dim in self.veto_dimensions:
                score = getattr(vote.scores, dim)
                if score < self.veto_threshold:
                    return AggregatedJudgment(
                        page_id=page_id, page_type=page_type,
                        votes=votes,
                        aggregated_scores=vote.scores,
                        aggregated_total=vote.total_score,
                        verdict="reject",
                        issues=vote.issues + [{
                            "dimension": dim, "severity": "critical",
                            "description": f"Veto: {vote.judge_name} scored {dim}={score:.2f}",
                        }],
                        improvement_suggestions="\n".join(
                            v.improvement_suggestions for v in votes if v.improvement_suggestions
                        ),
                        judged_at=int(time.time() * 1000),
                        llm_call_count=sum(v.llm_call_count for v in votes),
                    )

        # Mean aggregation
        dim_names = [
            "source_type_appropriateness", "factuality", "completeness",
            "clarity", "readability", "searchability",
        ]
        aggregated_scores = JudgmentScores(
            **{dim: sum(getattr(v.scores, dim) for v in votes) / len(votes) for dim in dim_names}
        )
        aggregated_total = compute_total(aggregated_scores, self.settings.weights)
        verdict = verdict_for(aggregated_total, self.settings)

        # Issues union (dedup by (dimension, description)).
        seen: set = set()
        all_issues = []
        for v in votes:
            for issue in v.issues:
                key = (issue.get("dimension"), issue.get("description"))
                if key not in seen:
                    seen.add(key)
                    all_issues.append(issue)

        return AggregatedJudgment(
            page_id=page_id, page_type=page_type,
            votes=votes,
            aggregated_scores=aggregated_scores,
            aggregated_total=aggregated_total,
            verdict=verdict,
            issues=all_issues,
            improvement_suggestions="\n".join(
                v.improvement_suggestions for v in votes if v.improvement_suggestions
            ),
            judged_at=int(time.time() * 1000),
            llm_call_count=sum(v.llm_call_count for v in votes),
        )


def _safe_scores(d: dict) -> JudgmentScores:
    keys = [
        "source_type_appropriateness", "factuality", "completeness",
        "clarity", "readability", "searchability",
    ]
    args: dict[str, float] = {}
    for k in keys:
        v = d.get(k, 0.0)
        try:
            f = float(v)
        except (TypeError, ValueError):
            f = 0.0
        if not (0.0 <= f <= 1.0):
            f = 0.0
        args[k] = f
    return JudgmentScores(**args)
