# Quality Gate v2.1 (Judge Ensemble) Design Spec

**Date:** 2026-07-21
**Status:** Approved (pending user sign-off)
**Target codebase:** ruflo-kb (Python 3.11+, master @ 5083a1b, post-Wiki-v2.1-polish spec)

## Goal

Extend Quality Gate v2.0's single-LLM judge with **multi-judge ensemble voting**. Each page is judged by 2-3 independent LLM judges (potentially from different providers), then their scores are combined via weighted averaging with veto logic.

This reduces single-judge bias (some LLM judges are too lenient on certain dimensions) and provides a more robust quality signal, at the cost of additional LLM calls.

## Non-goals

- No model disagreement visualization (deferred).
- No per-dimension judge specialization (each judge scores all 6 dimensions).
- No ensemble training / fine-tuning (deferred).
- No cross-project judge sharing.


## Input Contract

> Reference: [`_input_contracts.md`](_input_contracts.md) for cross-spec dependency map.

**This spec provides** (consumed by other specs):

- Multi-judge ensemble voting
- `EnsembleJudge`
- `JudgeVote` + `AggregatedJudgment`
- Per-dimension mean + veto logic

**This spec requires from other specs**:

- **Quality Gate v2.0 (REQUIRED)**: `JudgmentScores`, `Judgment`
- **Multi-Provider LLM (REQUIRED)**: multiple provider registry entries

**Phase**: Phase 4 — Advanced
**Priority**: P2 — v2.1 experiment

## Architecture

```
Generator → page batch
   │
   ▼
QualityJudge.judge_batch (extended)
   │
   ▼
For each page:
   1. Determine judges list:
      - Primary: ctx.settings.llm.provider_registry_name
      - Additional: ctx.settings.quality.ensemble_judges (if non-empty)
      - If ensemble_judges == [] AND ensemble_enabled == false: single-judge mode (v2.0 behavior)
      - If ensemble_enabled == true AND only 1 judge configured: log warning + single-judge mode
   2. Run all judges in parallel (asyncio.gather)
   3. Aggregate scores:
      - per-dimension mean
      - per-dimension min (veto: if any judge gives <0.2 on factuality, treat as hard_reject)
      - overall mean
   4. verdict_for(aggregated_scores, settings.quality) — same thresholds as v2.0
   5. Issues: union of all judges' issues (dedup by description)
   6. improvement_suggestions: concatenated from all judges
```

## Components

### New modules

```
src/quality/ensemble.py           # EnsembleJudge + aggregation
tests/test_quality/test_ensemble.py
```

### Modified modules

| Path | Change |
|---|---|
| `src/project/settings.py` | `QualitySettings` add `ensemble_enabled: bool = True` + `ensemble_judges: list[str] = []` |
| `src/pipeline/judge.py` | `QualityJudge.judge_batch` extended to use ensemble when enabled |

## Data structures

```python
# src/project/settings.py
@dataclass
class QualitySettings:
    enabled: bool = True
    weights: dict[str, float] = field(default_factory=lambda: {...})
    threshold_hard_reject: float = 0.4
    threshold_reject: float = 0.6
    threshold_warn: float = 0.8
    max_retries_for_reject: int = 2
    max_retries_for_hard_reject: int = 1
    
    # NEW
    ensemble_enabled: bool = True
    ensemble_judges: list[str] = field(default_factory=list)   # e.g. ["anthropic", "ollama"]
    ensemble_min_score_veto: float = 0.2                     # any judge < this on factuality → hard_reject
```

```python
# src/quality/ensemble.py
@dataclass
class JudgeVote:
    judge_name: str                              # "openai" | "anthropic" | "ollama"
    model: str                                  # "gpt-4o-mini" | etc.
    scores: JudgmentScores
    total_score: float
    issues: list[JudgmentIssue]
    improvement_suggestions: str
    judged_at: int
    llm_call_count: int = 1

@dataclass
class AggregatedJudgment:
    page_id: str
    page_type: str
    votes: list[JudgeVote]
    aggregated_scores: JudgmentScores          # mean across votes
    aggregated_total: float
    verdict: str                                # computed from aggregated_total
    issues: list[JudgmentIssue]                 # union of all votes
    improvement_suggestions: str                # concatenated
    judged_at: int
    llm_call_count: int                         # sum across votes

class EnsembleJudge:
    def __init__(self, settings: QualitySettings, registry: ProviderRegistry):
        self.settings = settings
        self.registry = registry
        self.veto_dimensions = {"factuality"}     # any judge < 0.2 on these → hard_reject
    
    def resolve_judges(self, ctx: ProjectContext) -> list[tuple[str, ProviderConfig, str]]:
        """Return list of (judge_name, provider_config, model_name)."""
        primary_name = ctx.settings.llm.provider_registry_name
        primary_config = self.registry.get(primary_name)
        primary_model = ctx.settings.llm.model or primary_config.default_chat_model
        
        judges = [(primary_name, primary_config, primary_model)]
        for additional_name in self.settings.ensemble_judges:
            if additional_name == primary_name:
                continue
            try:
                config = self.registry.get(additional_name)
                model = config.default_chat_model
                judges.append((additional_name, config, model))
            except ProviderNotFoundError:
                pass  # skip silently
        
        if self.settings.ensemble_enabled and len(judges) < 2:
            logger.warning("[Judge] ensemble_enabled=true but only 1 judge available")
        return judges
    
    async def judge_page(self, ctx: ProjectContext, page: WikiPage, analysis: AnalysisResult) -> AggregatedJudgment:
        judges = self.resolve_judges(ctx)
        
        async def vote_one(name: str, config: ProviderConfig, model: str) -> JudgeVote:
            provider = create_llm_provider(name, model_override=model)
            judge_prompt = build_judge_prompt(page, analysis)
            response = await provider.complete(
                prompt=judge_prompt,
                response_format=JUDGE_RESPONSE_SCHEMA,
            )
            scores = JudgmentScores.from_dict(response["scores"])
            total = compute_total(scores, self.settings.weights)
            return JudgeVote(
                judge_name=name,
                model=model,
                scores=scores,
                total_score=total,
                issues=[JudgmentIssue(**i) for i in response.get("issues", [])],
                improvement_suggestions=response.get("improvement_suggestions", ""),
                judged_at=int(time.time() * 1000),
            )
        
        votes = await asyncio.gather(*[vote_one(n, c, m) for n, c, m in judges])
        return self._aggregate(page, votes)
    
    def _aggregate(self, page: WikiPage, votes: list[JudgeVote]) -> AggregatedJudgment:
        # Veto check: any judge < min on veto dimensions
        for vote in votes:
            for dim in self.veto_dimensions:
                score = getattr(vote.scores, dim)
                if score < self.settings.ensemble_min_score_veto:
                    return AggregatedJudgment(
                        page_id=page.id,
                        page_type=str(page.type),
                        votes=votes,
                        aggregated_scores=vote.scores,           # use vetoed score
                        aggregated_total=vote.total_score,
                        verdict="hard_reject",
                        issues=vote.issues + [
                            JudgmentIssue(
                                dimension=dim,
                                severity="critical",
                                description=f"Veto: {vote.judge_name} scored {dim}={score:.2f} (< {self.settings.ensemble_min_score_veto})",
                            )
                        ],
                        improvement_suggestions="\n".join(v.improvement_suggestions for v in votes if v.improvement_suggestions),
                        judged_at=int(time.time() * 1000),
                        llm_call_count=sum(v.llm_call_count for v in votes),
                    )
        
        # Mean aggregation
        dim_names = ["source_type_appropriateness", "factuality", "completeness", "clarity", "readability", "searchability"]
        aggregated_scores = JudgmentScores(
            **{dim: sum(getattr(v.scores, dim) for v in votes) / len(votes) for dim in dim_names}
        )
        aggregated_total = compute_total(aggregated_scores, self.settings.weights)
        verdict = verdict_for(aggregated_total, self.settings)
        
        # Issues union (dedup by description)
        seen = set()
        all_issues = []
        for v in votes:
            for issue in v.issues:
                key = (issue.dimension, issue.description)
                if key not in seen:
                    seen.add(key)
                    all_issues.append(issue)
        
        return AggregatedJudgment(
            page_id=page.id,
            page_type=str(page.type),
            votes=votes,
            aggregated_scores=aggregated_scores,
            aggregated_total=aggregated_total,
            verdict=verdict,
            issues=all_issues,
            improvement_suggestions="\n".join(v.improvement_suggestions for v in votes if v.improvement_suggestions),
            judged_at=int(time.time() * 1000),
            llm_call_count=sum(v.llm_call_count for v in votes),
        )
```

## CLI

```
python -m src.cli quality config set ensemble_enabled true
python -m src.cli quality config set ensemble_judges anthropic ollama
```

No new CLI commands; `cmd_quality_score` shows ensemble breakdown.

## Error handling

| Stage | Error | Strategy |
|---|---|---|
| Judge resolution | Additional provider not configured | Skip + warning; if only 1 judge left, log "ensemble degraded to single" |
| One judge fails | LLM timeout / JSON parse fail | That judge's vote marked as `failed`; remaining votes aggregated |
| All judges fail | All LLM calls fail | Same as v2.0 hard_reject + quarantine |
| Veto dimension | Any judge < 0.2 on factuality | Direct hard_reject; skip retry (don't waste budget) |
| Cost | Ensemble 3x LLM cost | Per settings.quality.ensemble_judges; user controls |

## Backwards compatibility

- `settings.quality.ensemble_enabled` defaults to `True` (with sensible auto-detected additional judges).
- If `ensemble_judges == []`, only primary judge is used (= v2.0 behavior). No breaking change for users who don't configure.
- Existing projects auto-detect additional judges from configured providers.

## Testing strategy

### Unit tests

| Module | Test focus |
|---|---|
| `src/quality/ensemble.py` | resolve_judges; aggregation; veto logic; single-judge fallback |
| `src/pipeline/judge.py` | judge_batch uses EnsembleJudge when enabled; v2.0 path when disabled |

### Integration tests

```
tests/test_integration/test_judge_ensemble.py:
    def test_three_judges_aggregate():
        # Mock 3 judges with different scores
        # Verify: aggregated_scores = mean; verdict = verdict_for(mean)

    def test_veto_on_low_factuality():
        # Mock judge 1: factuality=0.9, judge 2: factuality=0.1
        # Verify: verdict = hard_reject (veto)

    def test_one_judge_failure_uses_others():
        # Mock judge 1: timeout, judge 2: success
        # Verify: aggregated from judge 2 only

    def test_ensemble_disabled_single_judge():
        # ensemble_enabled=false, ensemble_judges=[]
        # Verify: same as v2.0 (single judge behavior)
```


## MVP Scope / Polish / Deferred

> This section partitions the spec's features into delivery tiers. See [`_input_contracts.md`](_input_contracts.md) for cross-spec context.

### MVP Scope (P2)

- Default 2 judges (primary + 1 configured)
- Mean aggregation
- Veto on factuality < 0.2

### Polish (v2.0.1 or later)

- Configurable judge count (2-3)
- Per-dimension judge specialization
- Judge A/B testing framework

### Deferred (v2.1+)

- Ensemble training via user feedback
- Model disagreement visualization UI
- Cross-project judge sharing

## Implementation order

2 phases:

1. **Foundation** — `QualitySettings.ensemble_*` fields + `EnsembleJudge` class + tests
2. **Integration** — `QualityJudge.judge_batch` uses EnsembleJudge + tests

## Cost estimation

- 2-3x LLM cost per page (per ensemble size).
- Lint semantic judge already has cache (Wiki v2.1 polish spec) — but quality judge doesn't, so each page re-judges on retry.

## Open questions / deferred

- Per-dimension judge specialization (different judges for different dimensions).
- Model disagreement visualization UI.
- Ensemble training via user feedback (which judge was right).
- Cross-project judge sharing.