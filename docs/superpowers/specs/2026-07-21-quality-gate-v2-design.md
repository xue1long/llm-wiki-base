# Quality Gate v2 (LLM-as-Judge) Design Spec

**Date:** 2026-07-21
**Status:** Approved (pending user sign-off)
**Target codebase:** ruflo-kb (Python 3.11+, master @ 7256c6f, post-HTTP-API spec)
**Inspired by:** llm_wiki-main's implicit LLM-driven semantic analysis (`lint.ts`)

## Goal

Replace ruflo-kb's brittle regex-based quality scoring (`calculate_quality_metrics` with `ad_ratio` / `text_density` / `fluency_score`) with a real LLM-as-judge quality gate that:

- Runs **synchronously inline** as the final step before Librarian archive
- Judges each generated wiki page on **6 weighted dimensions** (source_type_appropriateness / factuality / completeness / clarity / readability / searchability)
- Returns a **4-tier verdict** (pass / warn / reject / hard_reject) computed deterministically from thresholds in `settings.quality`
- Supports **per-page retry** (2 retries for regular rejects, 1 retry for hard_rejects) with low-temperature regeneration + judge feedback in the prompt
- Quarantines rejected pages to `.index/quarantine/<task_id>/<slug>.md` with sidecar judgment JSON for later review / retry / discard
- Generates `quality-warn` review items for pages that pass but with caveats (new review type)
- Is fully bypassable via `quality.enabled=false` (page directly passes) or `--no-judge` CLI flag (one-shot bypass)
- Adds CLI commands: `quarantine list/retry/discard`, `quality score`, `quality config show/set`

## Non-goals

- No streaming judge output (deferred).
- No per-task level retry budget (per-page granularity is sufficient).
- No judge ensemble (multiple LLMs voting). Single LLM with retry is sufficient.
- No real-time judge observability / dashboard.
- No automated retraining of judge prompts based on user feedback.
- The legacy `calculate_quality_metrics` is **fully deleted** — not available as a fallback.
- No migration of existing v1.0 frontmatter `quality_score` / `ad_ratio` / `text_density` / `fluency_score` fields (they're stripped on first access; schema migration handles this in wiki v2.0).

## Architecture

### Pipeline integration

```
collector:start
  └─► Collector.collect          → 写 raw/sources/<task_id>.<ext>
       └─► COLLECTOR_DONE

COLLECTOR_DONE  →  Analyzer.analyze
  └─► 写 .index/analysis_cache/<task_id>.json
  └─► ANALYZER_DONE

ANALYZER_DONE  →  Generator.generate
  └─► 调 LLM 生成页面 JSON
  └─► page_writer 写 wiki/<type>/<slug>.md
  └─► wikilink 二次校验
  └─► indexer / logger 更新
  └─► GENERATOR_DONE

GENERATOR_DONE  →  ⭐ QualityJudge.judge_batch (新增)
  └─► 同步 inline：调 LLM 评判每页（max 3 calls per page: 1 initial + 2 retries）
  └─► 通过 (pass / warn) → 页面保留（warn 加 quality_warning: true）
  └─► Reject → 触发 Generator.regenerate_one_page 带 feedback
  └─► Hard_reject → 1 次 retry；仍 fail → quarantine
  └─► Reject retry 2 次仍 fail → quarantine
  └─► QUALITY_JUDGED

QUALITY_JUDGED → Orchestrator._on_quality_judged
  └─► update_task_status(APPROVED if any page passed, REJECTED if all failed)
  └─► Librarian.archive        → embed 入库
       └─► LIBRARIAN_DONE
```

### Judge pipeline detail

```python
async def judge_batch(ctx, pages, analysis) -> BatchJudgmentResult:
    if not ctx.settings.quality.enabled:
        return BatchJudgmentResult(judgments={}, pages_passed=[p.id for p in pages], ...)

    judgments = {}
    pending = list(pages)
    retry_counts = {p.id: 0 for p in pages}
    
    # max retries: regular=2, hard_reject=1 (computed per-page after first judgment)
    while pending:
        batch = await asyncio.gather(*[judge_one(ctx, p, analysis) for p in pending])
        for page, judgment in zip(pending, batch):
            judgments[page.id] = judgment
            verdict = verdict_for(judgment, ctx.settings.quality)
            page.quality_scores = asdict(judgment.scores)
            
            if verdict in ("pass", "warn"):
                if verdict == "warn":
                    page.quality_warning = True
                    review_items.append(make_quality_warn_item(page, judgment))
                continue
            
            # reject or hard_reject
            max_retries = 1 if verdict == "hard_reject" else 2
            if retry_counts[page.id] >= max_retries:
                # Quarantine directly
                quarantine.put(ctx, page, judgment)
                continue
            
            retry_counts[page.id] += 1
            new_page = await ctx.generator.regenerate_one_page(
                page_id=page.id,
                analysis=analysis,
                feedback=judgment.improvement_suggestions,
                issues=judgment.issues,
                temperature_override=0.3,    # ↓ from 0.7 for stability
            )
            pending.append(new_page)        # judge will retry in next loop iteration
        pending = [p for p in pending if retry_counts[p.id] > 0 and judgments[p.id] not in final state]
    ...
```

### Verdict computation

```python
def verdict_for(scores: JudgmentScores, quality: QualitySettings) -> str:
    total = compute_total(scores, quality.weights)
    if total >= quality.threshold_warn:        # default 0.8
        return "pass"
    if total >= quality.threshold_reject:      # default 0.6
        return "warn"
    if total >= quality.threshold_hard_reject: # default 0.4
        return "reject"
    return "hard_reject"
```

### Quarantine storage

```
.index/quarantine/<task_id>/
├── foo-bar.md                # rejected page content (with frontmatter)
├── foo-bar.judgment.json     # judgment sidecar (Judgment.to_json())
├── baz.md
└── baz.judgment.json
```

`quarantine retry <task_id> <slug>` moves the page back to `wiki/<type>/<slug>.md` with `quality_warning: true` frontmatter (manual override of judgment).

## Components

### New modules

| Path | Responsibility |
|---|---|
| `src/quality/__init__.py` | Public API |
| `src/quality/scoring.py` | `compute_total(scores, weights)` + `verdict_for(scores, settings)` |
| `src/pipeline/prompts/judge.py` | Judge prompt + `PROMPT_VERSION = "2026-07-21-v1"` |
| `src/pipeline/judge.py` | `QualityJudge.judge_batch` + `judge_one` + retry coordination |
| `src/pipeline/quarantine.py` | `QuarantineStore.put/list/get/discard/retry` |
| `src/cli_ext/quality_cmd.py` | `cmd_quarantine_list/retry/discard`, `cmd_quality_score`, `cmd_quality_config_show/set` |
| `tests/test_quality/__init__.py` | |
| `tests/test_quality/test_scoring.py` | compute_total + verdict_for boundary tests |
| `tests/test_pipeline/test_judge.py` | judge_one / judge_batch orchestration |
| `tests/test_pipeline/test_judge_retry.py` | retry budget enforcement; hard_reject vs reject |
| `tests/test_pipeline/test_quarantine.py` | put/list/get/discard/retry |
| `tests/test_pipeline/test_prompts_judge.py` | prompt construction + response schema |
| `tests/test_cli_ext/test_cmd_quarantine.py` | |
| `tests/test_cli_ext/test_cmd_quality_score.py` | |
| `tests/test_integration/test_quality_pipeline.py` | End-to-end: GENERATOR_DONE → QUALITY_JUDGED → LIBRARIAN_DONE |

### Modified modules

| Path | Change |
|---|---|
| `src/types.py` | `WikiPage` adds `quality_warning: bool = False` + `quality_scores: dict[str, float] | None = None`; `KnowledgeTask` adds `quarantine_pages: list[str] = []` |
| `src/events/events.py` | `EventName.QUALITY_JUDGED` + `QualityJudgedPayload(task_id, pages, quarantined, warnings, judgments)` |
| `src/events/events.py` | `ReviewItem.type` enum adds `quality-warn` value |
| `src/pipeline/pipeline.py` | Insert `GENERATOR_DONE → QualityJudge.judge_batch → QUALITY_JUDGED` bridge |
| `src/pipeline/processor.py` (Generator) | Add `regenerate_one_page(page_id, analysis, feedback, issues, temperature_override)` method |
| `src/orchestrator/orchestrator.py` | `_on_quality_judged` handler: decide APPROVED/REJECTED + trigger Librarian |
| `src/orchestrator/audit_hard.py` | Frontmatter schema validation: optional `quality_warning` field + `quality_scores` dict |
| `src/project/settings.py` | `ProjectSettings` adds `quality: QualitySettings` block |
| `src/cli.py` | `ingest --no-judge` flag (one-shot bypass); pass through to QualityJudge |
| `src/pipeline/processor.py` | **DELETE** old `calculate_quality_metrics()` function |
| `src/orchestrator/audit_hard.py` | **DELETE** old `QUALITY_SCORE_THRESHOLD = 0.6` constant |
| `src/wiki/review.py` | Add `quality-warn` review item creation helper |

### Deleted modules

- `src/pipeline/processor.py::calculate_quality_metrics()` (regex-based scoring) — fully deleted

## Data structures

```python
# src/pipeline/judge.py
@dataclass
class JudgmentScores:
    source_type_appropriateness: float       # 0.0-1.0
    factuality: float
    completeness: float
    clarity: float
    readability: float
    searchability: float

    @staticmethod
    def from_dict(d: dict) -> "JudgmentScores":
        return JudgmentScores(**{k: float(d[k]) for k in [
            "source_type_appropriateness", "factuality", "completeness",
            "clarity", "readability", "searchability",
        ]})

@dataclass
class JudgmentIssue:
    dimension: str                            # 6 维度之一
    severity: Literal["minor", "major", "critical"]
    description: str                          # ≤ 200 字

@dataclass
class Judgment:
    page_id: str
    page_type: str
    scores: JudgmentScores
    total_score: float                        # 0.0-1.0, computed by code
    verdict: Literal["pass", "warn", "reject", "hard_reject"]
    issues: list[JudgmentIssue]
    improvement_suggestions: str              # ≤ 200 字
    judged_at: int
    llm_call_count: int                       # 1, 2, or 3

    def to_json(self) -> str: ...
    @classmethod
    def from_json(cls, raw: str) -> "Judgment": ...

@dataclass
class BatchJudgmentResult:
    judgments: dict[str, Judgment]            # slug → Judgment
    pages_passed: list[str]                   # verdict == "pass"
    pages_warned: list[str]                   # verdict == "warn"
    pages_quarantined: list[str]              # hard_reject OR retry-exhausted
    pages_retried: list[str]                  # retry attempted at least once
```

```python
# src/pipeline/quarantine.py
@dataclass
class QuarantinedPage:
    slug: str
    task_id: str
    page_type: str
    content: str                              # full markdown with frontmatter
    judgment: Judgment
    quarantined_at: int

class QuarantineStore:
    QUARANTINE_DIR = ".index/quarantine"
    
    def put(self, ctx: ProjectContext, page: WikiPage, judgment: Judgment) -> Path: ...
    def list(self, ctx: ProjectContext, task_id: str | None = None) -> list[QuarantinedPage]: ...
    def get(self, ctx: ProjectContext, task_id: str, slug: str) -> QuarantinedPage: ...
    def discard(self, ctx: ProjectContext, task_id: str, slug: str) -> None: ...
    def retry(self, ctx: ProjectContext, task_id: str, slug: str) -> None:
        """Move page back to wiki/<type>/<slug>.md with quality_warning: true."""
```

```python
# src/project/settings.py
@dataclass
class QualitySettings:
    enabled: bool = True
    weights: dict[str, float] = field(default_factory=lambda: {
        "source_type_appropriateness": 0.15,
        "factuality": 0.30,
        "completeness": 0.20,
        "clarity": 0.15,
        "readability": 0.10,
        "searchability": 0.10,
    })
    threshold_hard_reject: float = 0.4        # < 0.4
    threshold_reject: float = 0.6            # 0.4-0.6
    threshold_warn: float = 0.8              # 0.6-0.8
    # retry policy:
    max_retries_for_reject: int = 2
    max_retries_for_hard_reject: int = 1
```

```python
# src/quality/scoring.py
def compute_total(scores: JudgmentScores, weights: dict[str, float]) -> float:
    total = 0.0
    for dim, w in weights.items():
        v = getattr(scores, dim)
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"Score out of range: {dim}={v}")
        total += w * v
    return round(total, 4)

def verdict_for(scores: JudgmentScores, quality: QualitySettings) -> str:
    total = compute_total(scores, quality.weights)
    if total >= quality.threshold_warn:
        return "pass"
    if total >= quality.threshold_reject:
        return "warn"
    if total >= quality.threshold_hard_reject:
        return "reject"
    return "hard_reject"
```

## LLM protocol

### Judge prompt input

```
<source_text>: 原始源文（截断到 4000 tokens）
<analysis_result_json>: AnalysisResult 完整 JSON
<generated_page_content>: 单页 markdown 内容（含 frontmatter）
<page_type>: source | entity | concept | synthesis | comparison
<quality_feedback>: （仅重试时）上次 judge 给的改进建议
```

### Judge prompt output (strict JSON)

```json
{
  "page_id": "<slug>",
  "page_type": "entity",
  "scores": {
    "source_type_appropriateness": 0.85,
    "factuality": 0.90,
    "completeness": 0.75,
    "clarity": 0.80,
    "readability": 0.85,
    "searchability": 0.70
  },
  "issues": [
    {"dimension": "completeness", "severity": "minor", "description": "..."}
  ],
  "improvement_suggestions": "<≤ 200 字>"
}
```

**Note**: `total_score` and `verdict` are **NOT** returned by LLM; computed deterministically by code using `settings.quality`.

### Constraints (hardcoded in prompt)

- Each score 0.0-1.0; reject scores outside range
- `issues` 0-5 entries; `severity` ∈ {"minor", "major", "critical"}
- `improvement_suggestions` ≤ 200 字

### Retry prompt template

```
The previous generated page was rejected by quality judge with this feedback:

{quality_feedback}

Issues identified:
{issues}

Please regenerate the page addressing these concerns. Maintain the same page id and type. The AnalysisResult and source remain unchanged.
```

## Error handling

| Stage | Error | Strategy |
|---|---|---|
| Judge LLM timeout (initial) | asyncio.TimeoutError | Treat as hard_reject; quarantine directly |
| Judge LLM timeout (retry) | asyncio.TimeoutError | Same; use retry budget |
| Judge JSON parse fail | schema mismatch | 1 retry with stricter prompt; if still fails, treat as hard_reject |
| Generator.regenerate_one_page LLM error | fails on retry | Use empty feedback fallback; second failure → quarantine |
| Quarantine write fail | `.index/quarantine/` not writable | task FAILED + log error |
| Quality disabled | `enabled=false` | Skip judge entirely; pages directly pass; `wiki_meta.json` records `quality_judged: false` |
| `--no-judge` flag | one-shot bypass | Same as disabled but only for this ingest |
| Threshold misconfiguration | `threshold_hard_reject > threshold_reject > threshold_warn` violated | Raise at settings load; startup fails |
| Page ID collision in quarantine | two quarantined pages same slug | Slug includes task_id suffix `quarantine/<task_id>/<slug>.md`; no collision |
| `quality score <page_path>` outside KB | Path not in any project | Error + hint `cd` into a project |
| `quality score <page_path>` on quarantined page | User runs score on quarantined content | Allow; display judgment.json sidecar if exists |
| hard_reject retry budget exhausted | 1 retry still hard_reject | Quarantine |
| reject retry budget exhausted | 2 retries still reject | Quarantine |

## CLI surface

```
python -m src.cli ingest <source> [--no-judge]                # --no-judge one-shot bypass
python -m src.cli quarantine list [--project <id>]             # list all quarantined pages
python -m src.cli quarantine show <task_id> <slug>             # show quarantined content + judgment
python -m src.cli quarantine retry <task_id> <slug>            # move back to wiki/ with quality_warning=true
python -m src.cli quarantine discard <task_id> <slug>          # permanently delete
python -m src.cli quality score <page_path>                    # run judge on existing page (single-shot)
python -m src.cli quality config show                          # print current thresholds + weights
python -m src.cli quality config set threshold_warn 0.85       # update setting
python -m src.cli quality config set weights.factuality 0.4    # update weight
python -m src.cli quality config reset                         # restore defaults
```

## Backwards compatibility

- **`calculate_quality_metrics` removed** — existing code that imports it will fail import; explicit error message directs users to migrate
- **`audit_hard.QUALITY_SCORE_THRESHOLD` removed** — replaced by `settings.quality.threshold_*`
- **v1.0 KB migration** — wiki v2.0 spec's v1→v2 migration already strips old `quality_score` / `ad_ratio` etc. from frontmatter; this spec adds the new `quality_warning` / `quality_scores` fields as optional
- **Old frontmatter fields** — `quality_score`, `ad_ratio`, `text_density`, `fluency_score` are silently ignored on read; not written by Generator

## Testing strategy

### Unit tests

| Module | Test focus |
|---|---|
| `src/quality/scoring.py` | `compute_total` weighted sum correctness; `verdict_for` 4-tier boundaries; invalid score → ValueError |
| `src/pipeline/prompts/judge.py` | prompt construction; response schema validation |
| `src/pipeline/judge.py` | `judge_one` returns Judgment; `judge_batch` retry budget enforcement |
| `src/pipeline/judge.py` | `quality.enabled=false` skips judge, pages directly pass |
| `src/pipeline/judge.py` | hard_reject uses 1 retry, reject uses 2 retries |
| `src/pipeline/quarantine.py` | put/list/get/discard/retry; retry moves to wiki/ with correct frontmatter |
| `src/pipeline/processor.py` | `regenerate_one_page` injects feedback + temperature override |
| `src/pipeline/pipeline.py` | event wiring: GENERATOR_DONE → QUALITY_JUDGED → LIBRARIAN_DONE |
| `src/events/events.py` | QualityJudgedPayload shape; ReviewItem type enum includes "quality-warn" |
| `src/project/settings.py` | QualitySettings load/save; threshold ordering validation |

### Integration test

```python
# tests/test_integration/test_quality_pipeline.py
async def test_full_pipeline_pass_path():
    # MockLLMProvider: analyzer → generator → judge (high scores) → librarian
    # Verify: page in wiki/, no quality_warning, no review_items

async def test_full_pipeline_warn_path():
    # Mock judge returns scores that produce "warn" verdict
    # Verify: page in wiki/ with quality_warning: true; review_items has quality-warn entry

async def test_full_pipeline_reject_retry_pass():
    # Mock: 1st judge = reject → generator retry → 2nd judge = pass
    # Verify: page in wiki/ (regenerated version); judgment has llm_call_count=2

async def test_full_pipeline_hard_reject_quarantine():
    # Mock: judge = hard_reject (1 retry) → still hard_reject → quarantine
    # Verify: page in .index/quarantine/<task_id>/<slug>.md + judgment sidecar

async def test_full_pipeline_disabled():
    # Mock: judge never called
    # Verify: page in wiki/; wiki_meta.json has quality_judged: false

async def test_full_pipeline_no_judge_flag():
    # Mock: judge never called for this ingest
    # Verify: page in wiki/ (same as disabled but only this ingest)
```

## Implementation order

8 phases, each independently committable:

1. **Foundation** — `src/quality/scoring.py` + `JudgmentScores` / `Judgment` dataclasses + `QualitySettings` + tests
2. **Judge prompt** — `src/pipeline/prompts/judge.py` + `PROMPT_VERSION` + prompt-construction tests
3. **Judge stage** — `src/pipeline/judge.py` + `QualityJudge.judge_batch` + `judge_one` + mock LLM tests
4. **Generator retry** — `src/pipeline/processor.py::regenerate_one_page` + tests
5. **Quarantine** — `src/pipeline/quarantine.py` + `QuarantineStore` + tests
6. **Pipeline integration** — events / payload / `pipeline.py` bridge / `orchestrator._on_quality_judged` + delete old `calculate_quality_metrics` + tests
7. **CLI** — `src/cli_ext/quality_cmd.py` (quarantine list/show/retry/discard, quality score, quality config) + `ingest --no-judge` flag + tests
8. **Integration** — `tests/test_integration/test_quality_pipeline.py` end-to-end

Each phase follows TDD per-task rhythm; one commit per task.

## Cost estimation

Per-page judge LLM call: ~2500 tokens in + ~500 tokens out.
Default model (gpt-4o-mini / claude-haiku-4-5): ~$0.005/call.

| Scenario | Judge calls | Total judge cost |
|---|---|---|
| 5 pages all pass (first try) | 5 | $0.025 |
| 2 pages reject, retry → pass | 5 + 2 = 7 | $0.035 |
| 1 page hard_reject, 1 retry → pass | 5 + 1 = 6 | $0.030 |
| 1 page reject, 2 retries → still reject → quarantine | 5 + 3 = 8 | $0.040 |
| 1 page hard_reject, 1 retry → hard_reject → quarantine | 5 + 1 = 6 | $0.030 |
| All hard_reject (no retries save) | 5 | $0.025 |
| Worst case (all retry-exhausted) | 5 + (2×3) + (3×1) = 14 | $0.070 |

Average per-source ingest: ~$0.03 additional cost over wiki v2.0 baseline.

## Open questions / deferred (v3.0+)

- **Judge ensemble (multi-LLM voting)** — different LLM providers vote; useful when judge bias is suspected
- **Streaming judge output (SSE)** — partial judgments as they're computed
- **Judge prompt A/B testing framework** — track which prompt version produces more stable verdicts
- **Real-time judge observability / dashboard** — `/admin/quality` page with judge stats
- **Per-page retry budget per-task** — global limit to prevent retry storms
- **Automated retraining of judge prompts** — analyze review_items feedback to improve prompts
- **Cross-page consistency check** — judge page B in context of pages A, C, D for consistency
- **Quality trend analysis** — track quality scores over time per project

## Dependency graph

```
src/quality/scoring.py                                    (no deps)
       │
       ▼
src/pipeline/prompts/judge.py                            (no deps)
       │
       ▼
src/pipeline/judge.py ──► src/pipeline/processor.py (regenerate_one_page)
       │                  ──► src/pipeline/schemas.py (AnalysisResult)
       │                  ──► src/types.py (WikiPage, KnowledgeTask)
       │                  ──► src/llm/base.py (complete_json)
       │
       ▼
src/pipeline/quarantine.py ──► src/types.py
       │
       ▼
src/events/events.py (EventName.QUALITY_JUDGED + QualityJudgedPayload + ReviewItem.type "quality-warn")
       │
       ▼
src/pipeline/pipeline.py (event bridge)
       │
       ▼
src/orchestrator/orchestrator.py (_on_quality_judged handler)

src/cli_ext/quality_cmd.py ──► src/pipeline/quarantine.py
                              ──► src/quality/scoring.py
                              ──► src/pipeline/judge.py
                              ──► src/project/settings.py
```