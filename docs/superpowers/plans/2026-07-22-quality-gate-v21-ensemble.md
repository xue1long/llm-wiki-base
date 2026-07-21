# Quality Gate v2.1 Ensemble Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** Multi-judge ensemble voting on top of Quality Gate v2.0. 2 judges (primary + 1 configured) by default. Per-dimension mean + veto logic. Configurable via `settings.quality.ensemble_judges` list.

**Tech Stack:** Python 3.11+, asyncio, dataclass, Multi-Provider LLM.

**MVP Scope** (per spec): 2 judges + mean aggregation + veto on factuality < 0.2.

---

### Task 1: EnsembleJudge + aggregation

**Files:** `src/quality/ensemble.py` + tests

```python
# src/quality/ensemble.py
"""Multi-judge ensemble voting for quality gate v2.1."""
import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from ..llm.provider_factory import create_llm_provider
from ..llm.registry import ProviderRegistry
from .types import Judgment, JudgmentScores, QualitySettings, compute_total, verdict_for
from .judge import JUDGE_PROMPT, QualityJudge


_logger = logging.getLogger(__name__)


@dataclass
class JudgeVote:
    judge_name: str
    model: str
    scores: JudgmentScores
    total_score: float
    issues: list[dict] = field(default_factory=list)
    improvement_suggestions: str = ""
    llm_call_count: int = 1


@dataclass
class AggregatedJudgment:
    page_id: str
    page_type: str
    votes: list[JudgeVote]
    aggregated_scores: JudgmentScores
    aggregated_total: float
    verdict: str
    issues: list[dict]
    improvement_suggestions: str
    judged_at: int
    llm_call_count: int


class EnsembleJudge:
    def __init__(self, ctx, settings: QualitySettings, ensemble_judges: Optional[list[str]] = None):
        self.ctx = ctx
        self.settings = settings
        self.ensemble_judges = ensemble_judges or []
        self.veto_dimensions = {"factuality"}
        self.veto_threshold = 0.2

    def resolve_judges(self) -> list[tuple[str, str]]:
        """Return list of (provider_name, model_override) tuples."""
        judges = []
        primary_name = self.ctx.settings.llm.provider_registry_name
        judges.append((primary_name, None))
        for name in self.ensemble_judges:
            if name != primary_name and name in ProviderRegistry.load():
                judges.append((name, None))
        if len(judges) < 2:
            _logger.warning(f"[ensemble] only {len(judges)} judge available; ensemble degraded to single")
        return judges

    async def judge_page(self, page, source_text: str) -> AggregatedJudgment:
        """Multi-judge: run N judges in parallel; aggregate."""
        judges = self.resolve_judges()
        async def vote_one(name, model):
            cfg = ProviderRegistry.get(name)
            provider = create_llm_provider(name, model_override=model)
            prompt = JUDGE_PROMPT.format(
                source_text=source_text[:3000],
                page_id=page.id, page_type=page.type.value, page_body=page.body[:2000],
            )
            response = await provider.complete(
                prompt=prompt,
                response_format={
                    "type": "object",
                    "properties": {
                        "scores": {"type": "object"},
                        "issues": {"type": "array"},
                        "improvement_suggestions": {"type": "string"},
                    },
                    "required": ["scores"],
                },
            )
            scores = JudgmentScores.from_dict(response.get("scores", {}))
            total = compute_total(scores, self.settings.weights)
            return JudgeVote(
                judge_name=name, model=cfg.default_chat_model,
                scores=scores, total_score=total,
                issues=response.get("issues", []),
                improvement_suggestions=response.get("improvement_suggestions", ""),
            )

        votes = await asyncio.gather(*[vote_one(n, m) for n, m in judges])

        # Veto check
        for vote in votes:
            for dim in self.veto_dimensions:
                score = getattr(vote.scores, dim)
                if score < self.veto_threshold:
                    return AggregatedJudgment(
                        page_id=page.id, page_type=page.type.value,
                        votes=votes, aggregated_scores=vote.scores, aggregated_total=vote.total_score,
                        verdict="reject",
                        issues=vote.issues + [{
                            "dimension": dim, "severity": "critical",
                            "description": f"Veto: {vote.judge_name} scored {dim}={score:.2f}",
                        }],
                        improvement_suggestions="\n".join(v.improvement_suggestions for v in votes),
                        judged_at=int(time.time() * 1000), llm_call_count=sum(v.llm_call_count for v in votes),
                    )

        # Mean aggregation
        dim_names = ["source_type_appropriateness", "factuality", "completeness",
                     "clarity", "readability", "searchability"]
        aggregated_scores = JudgmentScores(
            **{dim: sum(getattr(v.scores, dim) for v in votes) / len(votes) for dim in dim_names}
        )
        aggregated_total = compute_total(aggregated_scores, self.settings.weights)
        verdict = verdict_for(aggregated_total, self.settings)

        # Issues union (dedup)
        seen = set()
        all_issues = []
        for v in votes:
            for issue in v.issues:
                key = (issue.get("dimension"), issue.get("description"))
                if key not in seen:
                    seen.add(key)
                    all_issues.append(issue)

        return AggregatedJudgment(
            page_id=page.id, page_type=page.type.value,
            votes=votes, aggregated_scores=aggregated_scores, aggregated_total=aggregated_total,
            verdict=verdict, issues=all_issues,
            improvement_suggestions="\n".join(v.improvement_suggestions for v in votes if v.improvement_suggestions),
            judged_at=int(time.time() * 1000),
            llm_call_count=sum(v.llm_call_count for v in votes),
        )
```

**Tests** (3): test_ensemble_default_2_judges, test_ensemble_veto_on_low_factuality, test_ensemble_aggregation_mean.

```bash
git add src/quality/ensemble.py tests/test_quality/test_ensemble.py
git commit -m "feat(quality): add EnsembleJudge (multi-judge voting + veto on factuality < 0.2)"
```

---

### Task 2: Wire into QualityJudge.judge_batch

**Files:** `src/quality/judge.py` upgrade + test

Modify `QualityJudge.__init__` to accept `ensemble_judges` param. In `judge_batch`, if `self.ensemble_judges` is set, use `EnsembleJudge` instead of single-call logic.

```python
# In judge.py
class QualityJudge:
    def __init__(self, ctx, settings: QualitySettings, ensemble_judges: Optional[list[str]] = None):
        self.ctx = ctx
        self.settings = settings
        self.ensemble_judges = ensemble_judges or []
        # ... existing init ...

    async def judge_batch(self, pages, source_texts):
        if self.ensemble_judges:
            from .ensemble import EnsembleJudge
            ensemble = EnsembleJudge(self.ctx, self.settings, self.ensemble_judges)
            # Run ensemble per page
            judgments = {}
            for page in pages:
                src = source_texts.get(page.id, "")
                agg = await ensemble.judge_page(page, src)
                # Convert AggregatedJudgment → Judgment
                judgments[page.id] = Judgment(
                    page_id=agg.page_id, page_type=agg.page_type,
                    scores=agg.aggregated_scores, total_score=agg.aggregated_total,
                    verdict=agg.verdict, issues=agg.issues,
                    improvement_suggestions=agg.improvement_suggestions,
                    judged_at=agg.judged_at, llm_call_count=agg.llm_call_count,
                )
            # ... return BatchJudgmentResult ...
```

**Test** (1): test_judge_batch_uses_ensemble_when_configured.

```bash
git add src/quality/judge.py tests/test_quality/test_judge.py
git commit -m "feat(quality): wire EnsembleJudge into QualityJudge.judge_batch"
```

---

## Self-Review

- [x] 2 judges default ✓
- [x] Mean aggregation ✓
- [x] Veto on factuality < 0.2 ✓
- [x] Configurable via `settings.quality.ensemble_judges` ✓

## Implementation order

Tasks 1-2 chain. Total: 2 tasks, ~1.5-2 hours.