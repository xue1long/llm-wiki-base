"""LLM-as-judge quality gate for wiki pages."""
import logging
import os
import time

from ..llm.provider_factory import create_llm_provider
from ..llm.registry import ProviderRegistry
from .types import (
    BatchJudgmentResult,
    Judgment,
    JudgmentScores,
    QualitySettings,
    compute_total,
    verdict_for,
)


_logger = logging.getLogger(__name__)


JUDGE_PROMPT = """You are judging the quality of a wiki page.

## Source text (for factuality check)
{source_text}

## Generated page
- ID: {page_id}
- Type: {page_type}
- Body:
{page_body}

## Task
Score this page on 6 dimensions (0.0-1.0 each). Output strict JSON:
{{
  "scores": {{
    "source_type_appropriateness": 0.0-1.0,
    "factuality": 0.0-1.0,
    "completeness": 0.0-1.0,
    "clarity": 0.0-1.0,
    "readability": 0.0-1.0,
    "searchability": 0.0-1.0
  }},
  "issues": [
    {{"dimension": "<dim>", "severity": "minor|major|critical", "description": "..."}}
  ],
  "improvement_suggestions": "<≤ 200 chars>"
}}
"""


class QualityJudge:
    """LLM-as-judge for batch of wiki pages.

    When ``ensemble_judges`` is non-empty, ``judge_batch`` delegates to
    :class:`EnsembleJudge` for multi-judge voting with mean aggregation +
    factuality veto. Single-judge mode (default) keeps the existing
    1-retry-per-page semantics.
    """

    def __init__(self, settings: QualitySettings, provider_registry_name: str = "openai",
                 ensemble_judges: list | None = None):
        self.settings = settings
        self.provider_registry_name = provider_registry_name
        self.ensemble_judges = ensemble_judges or []
        self.provider = create_llm_provider(provider_registry_name)

    async def judge_page(self, page_id: str, page_type: str, page_body: str,
                         source_text: str = "") -> Judgment:
        """Judge a single page. Returns Judgment with verdict.

        ``page_body`` and ``source_text`` may be plain strings — the CLI subcommand
        passes file contents without depending on the (not-yet-implemented) wiki
        page parser.
        """
        prompt = JUDGE_PROMPT.format(
            source_text=(source_text or "")[:3000],
            page_id=page_id,
            page_type=page_type,
            page_body=(page_body or "")[:2000],
        )
        # Providers return either LLMResponse or a dict (legacy OpenAIProvider).
        # We accept both: extract the actual JSON dict either way.
        response = await self.provider.complete(prompt=prompt)
        if hasattr(response, "content"):
            raw = response.content
        else:
            raw = response
        # Tolerate LLM wrapping JSON in ```...``` fences.
        if "```" in raw:
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.split("```", 1)[0]
        import json
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            data = {}

        scores_dict = data.get("scores", {}) if isinstance(data, dict) else {}
        scores = _safe_scores(scores_dict)
        total = compute_total(scores, self.settings.weights)
        return Judgment(
            page_id=page_id,
            page_type=page_type,
            scores=scores,
            total_score=total,
            verdict=verdict_for(total, self.settings),
            issues=data.get("issues", []) if isinstance(data, dict) else [],
            improvement_suggestions=data.get("improvement_suggestions", "") if isinstance(data, dict) else "",
            judged_at=int(time.time() * 1000),
            llm_call_count=1,
        )

    async def judge_batch(self, pages: list, source_texts: dict | None = None) -> BatchJudgmentResult:
        """Judge all pages; retry rejected ones; quarantine final rejects.

        If ``self.ensemble_judges`` is non-empty, delegates each page to
        :class:`EnsembleJudge` (no retry — veto is the hard stop).

        ``pages`` is a list of dicts with keys ``id`` / ``type`` / ``body`` so the
        judge doesn't require the wiki types module.
        """
        source_texts = source_texts or {}
        judgments: dict[str, Judgment] = {}
        pages_passed: list[str] = []
        pages_rejected: list[str] = []
        pages_quarantined: list[str] = []

        if self.ensemble_judges:
            # Multi-judge path: no retry; veto replaces retry semantics.
            from .ensemble import EnsembleJudge
            ensemble = EnsembleJudge(
                self.settings,
                ensemble_judges=self.ensemble_judges,
                primary_provider=self.provider_registry_name,
            )
            for page in pages:
                pid = page["id"]
                ptype = page.get("type", "entity")
                body = page.get("body", "")
                src = source_texts.get(pid, "")
                agg = await ensemble.judge_page(pid, ptype, body, src)
                j = Judgment(
                    page_id=agg.page_id,
                    page_type=agg.page_type,
                    scores=agg.aggregated_scores,
                    total_score=agg.aggregated_total,
                    verdict=agg.verdict,
                    issues=agg.issues,
                    improvement_suggestions=agg.improvement_suggestions,
                    judged_at=agg.judged_at,
                    llm_call_count=agg.llm_call_count,
                )
                judgments[pid] = j
                if j.verdict == "pass":
                    pages_passed.append(pid)
                else:
                    pages_quarantined.append(pid)
                    pages_rejected.append(pid)
            return BatchJudgmentResult(
                pages=judgments,
                pages_passed=pages_passed,
                pages_rejected=pages_rejected,
                pages_quarantined=pages_quarantined,
            )

        # Single-judge path: 1 retry per page (MVP semantics).
        for page in pages:
            pid = page["id"]
            src = source_texts.get(pid, "")
            judgment = await self.judge_page(pid, page.get("type", "entity"), page.get("body", ""), src)
            judgments[pid] = judgment
            if judgment.verdict == "pass":
                pages_passed.append(pid)
                continue
            # 1 retry (MVP)
            retry_judgment = await self.judge_page(pid, page.get("type", "entity"), page.get("body", ""), src)
            retry_judgment.llm_call_count = 2
            judgments[pid] = retry_judgment
            if retry_judgment.verdict == "pass":
                pages_passed.append(pid)
            else:
                pages_quarantined.append(pid)
                pages_rejected.append(pid)

        return BatchJudgmentResult(
            pages=judgments,
            pages_passed=pages_passed,
            pages_rejected=pages_rejected,
            pages_quarantined=pages_quarantined,
        )


def _safe_scores(d: dict) -> JudgmentScores:
    """Build JudgmentScores with defaults for missing dimensions.

    Returns 0.0 for any dimension missing in ``d`` or out of [0,1] range.
    """
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
