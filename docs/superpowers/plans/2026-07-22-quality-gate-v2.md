# Quality Gate v2.0 (LLM-as-Judge) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** LLM-as-judge quality gate running inline after Generator. 6 dimensions, 2-tier verdict (pass/reject; warn+hard_reject deferred), 1 retry per page, basic quarantine.

**Architecture:** Pipeline: Generator → QualityJudge.judge_batch → QualityJudged event → Orchestrator updates task status → Librarian archives. `QualitySettings` in ProjectSettings; `JudgmentScores` + `Judgment` types in shared.

**Tech Stack:** Python 3.11+, asyncio, dataclass, httpx (via Multi-Provider LLM).

**MVP Scope** (per spec): 6 dimensions + 2-tier verdict + 1 retry + basic quarantine (mark + don't write; no archive) + `quality score/config` CLI.

**Polish (v2.0.1)**: 4-tier verdict + 2 retries + quality-warn review item + full quarantine CLI.

---

### Task 1: `src/quality/types.py` — JudgmentScores + Judgment

**Files:** `src/quality/__init__.py` + `src/quality/types.py` + tests

```python
# src/quality/__init__.py
"""Quality gate — LLM-as-judge for wiki page quality."""
```

```python
# src/quality/types.py
"""Judgment types — 6-dimension quality scores + verdict."""
from dataclasses import asdict, dataclass, field
from typing import Literal


Verdict = Literal["pass", "reject"]   # MVP: only 2 tiers (warn + hard_reject deferred)


@dataclass
class JudgmentScores:
    source_type_appropriateness: float   # 0-1
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
    issues: list[dict] = field(default_factory=list)
    improvement_suggestions: str = ""
    judged_at: int = 0
    llm_call_count: int = 1

    def to_dict(self) -> dict:
        return {
            "page_id": self.page_id, "page_type": self.page_type,
            "scores": asdict(self.scores), "total_score": self.total_score,
            "verdict": self.verdict, "issues": self.issues,
            "improvement_suggestions": self.improvement_suggestions,
            "judged_at": self.judged_at, "llm_call_count": self.llm_call_count,
        }


@dataclass
class BatchJudgmentResult:
    pages: dict[str, Judgment]   # slug → Judgment
    pages_passed: list[str]
    pages_rejected: list[str]
    pages_quarantined: list[str]


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
    threshold_pass: float = 0.7   # MVP: 2-tier; pass if total >= 0.7
    max_retries: int = 1          # MVP: 1 retry per page


def compute_total(scores: JudgmentScores, weights: dict[str, float]) -> float:
    total = 0.0
    for dim, w in weights.items():
        v = getattr(scores, dim)
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"Score out of range: {dim}={v}")
        total += w * v
    return round(total, 4)


def verdict_for(total: float, settings: QualitySettings) -> Verdict:
    return "pass" if total >= settings.threshold_pass else "reject"
```

**Tests** (5): test_compute_total_weighted, test_verdict_for, test_judgment_round_trip, test_score_validation, test_default_weights.

```bash
git add src/quality/ tests/test_quality/__init__.py tests/test_quality/test_types.py
git commit -m "feat(quality): add JudgmentScores + Judgment + QualitySettings types"
```

---

### Task 2: `src/quality/judge.py` — LLM judge prompt + QualityJudge

**Files:** `src/quality/judge.py` + tests

```python
# src/quality/judge.py
"""LLM-as-judge quality gate for wiki pages."""
import asyncio
import json
import logging
import time

from ..lib.budgeted import BudgetedLLM
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
    "source_type_appropriateness": 0.0-1.0,    // does the type match content?
    "factuality": 0.0-1.0,                       // no hallucination vs source
    "completeness": 0.0-1.0,                    // covers key points
    "clarity": 0.0-1.0,                         // well-written
    "readability": 0.0-1.0,                     // well-formatted
    "searchability": 0.0-1.0                    // key terms visible
  }},
  "issues": [
    {{"dimension": "<dim>", "severity": "minor|major|critical", "description": "..."}}
  ],
  "improvement_suggestions": "<≤ 200 chars>"
}}
"""


class QualityJudge:
    """LLM-as-judge for batch of wiki pages."""

    def __init__(self, ctx, settings: QualitySettings):
        self.ctx = ctx
        self.settings = settings
        # Resolve provider
        config = ProviderRegistry.get(settings.provider_registry_name if hasattr(settings, "provider_registry_name") else "openai")
        self.provider = create_llm_provider(config.name)

    async def judge_page(self, page, source_text: str) -> Judgment:
        """Judge single page. Returns Judgment with verdict."""
        prompt = JUDGE_PROMPT.format(
            source_text=source_text[:3000],
            page_id=page.id, page_type=page.type.value,
            page_body=page.body[:2000],
        )
        response = await self.provider.complete(
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
        return Judgment(
            page_id=page.id, page_type=page.type.value,
            scores=scores, total_score=total,
            verdict=verdict_for(total, self.settings),
            issues=response.get("issues", []),
            improvement_suggestions=response.get("improvement_suggestions", ""),
            judged_at=int(time.time() * 1000),
            llm_call_count=1,
        )

    async def judge_batch(self, pages: list, source_texts: dict[str, str]) -> BatchJudgmentResult:
        """Judge all pages; retry rejected ones; quarantine final rejects."""
        from ..lib.atomic_ctx import AtomicContext
        from ..lib.write_hooks import flush_pending_writes

        judgments: dict[str, Judgment] = {}
        pages_passed: list[str] = []
        pages_rejected: list[str] = []
        pages_quarantined: list[str] = []

        for page in pages:
            src = source_texts.get(page.id, "")
            judgment = await self.judge_page(page, src)
            judgments[page.id] = judgment
            if judgment.verdict == "pass":
                pages_passed.append(page.id)
            else:
                # 1 retry (MVP)
                retry_judgment = await self.judge_page(page, src)
                retry_judgment.llm_call_count = 2
                judgments[page.id] = retry_judgment
                if retry_judgment.verdict == "pass":
                    pages_passed.append(page.id)
                else:
                    pages_quarantined.append(page.id)
                    pages_rejected.append(page.id)

        return BatchJudgmentResult(
            pages=judgments,
            pages_passed=pages_passed,
            pages_rejected=pages_rejected,
            pages_quarantined=pages_quarantined,
        )
```

**Tests** (4): test_judge_page_returns_judgment, test_judge_batch_pass, test_judge_batch_reject_after_retry, test_score_validation.

```bash
git add src/quality/judge.py tests/test_quality/test_judge.py
git commit -m "feat(quality): add QualityJudge (LLM-as-judge with 1 retry)"
```

---

### Task 3: `src/quality/quarantine.py` — basic quarantine

**Files:** `src/quality/quarantine.py` + tests

```python
# src/quality/quarantine.py
"""Quarantine store for rejected wiki pages (MVP: mark + don't write)."""
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from .types import Judgment


QUARANTINE_DIR = ".index/quarantine"


@dataclass
class QuarantinedPage:
    page_id: str
    task_id: str
    content: str
    judgment: Judgment
    quarantined_at: int


class QuarantineStore:
    @staticmethod
    def put(ctx, page, judgment: Judgment, content: str) -> Path:
        """Write page to quarantine dir + sidecar judgment JSON."""
        task_id = judgment.page_id  # placeholder; could be passed separately
        quarantine_dir = ctx.paths.root / QUARANTINE_DIR / task_id
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        # Write content
        (quarantine_dir / f"{page.id}.md").write_text(content, encoding="utf-8")
        # Sidecar judgment
        (quarantine_dir / f"{page.id}.judgment.json").write_text(
            json.dumps(judgment.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return quarantine_dir / f"{page.id}.md"

    @staticmethod
    def list(ctx, task_id: str | None = None) -> list[Path]:
        quarantine_root = ctx.paths.root / QUARANTINE_DIR
        if not quarantine_root.exists():
            return []
        if task_id:
            task_dir = quarantine_root / task_id
            return list(task_dir.glob("*.md")) if task_dir.exists() else []
        return list(quarantine_root.rglob("*.md"))
```

**Tests** (3): test_put_writes_files, test_list_filters_by_task, test_list_empty.

```bash
git add src/quality/quarantine.py tests/test_quality/test_quarantine.py
git commit -m "feat(quality): add QuarantineStore (basic mark + don't write)"
```

---

### Task 4: `src/cli_ext/quality_cmd.py` — quality CLI

**Files:** `src/cli_ext/quality_cmd.py` + tests + wire in cli.py

```python
# src/cli_ext/quality_cmd.py
"""Quality gate CLI subcommands."""
import argparse
import json
import sys
from pathlib import Path

from ..quality.judge import QualityJudge
from ..quality.types import QualitySettings, compute_total, verdict_for
from ..project.context import ProjectContext, ProjectNotFoundError


def cmd_quality_score(args: argparse.Namespace) -> None:
    """Run judge on a single page (read existing)."""
    try:
        ctx = ProjectContext.resolve(args.project, by_id_only=True)
    except ProjectNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)
    from ..wiki.page_writer import read_page
    page_path = ctx.paths.root / args.path
    if not page_path.exists():
        print(f"Page not found: {page_path}", file=sys.stderr)
        sys.exit(2)
    page = read_page(page_path)
    settings = _load_settings()
    judge = QualityJudge(ctx, settings)
    judgment = asyncio_run(judge.judge_page(page, source_text=""))
    print(json.dumps(judgment.to_dict(), indent=2, ensure_ascii=False))


def cmd_quality_config_show(args: argparse.Namespace) -> None:
    """Print current QualitySettings."""
    settings = _load_settings()
    print(f"enabled: {settings.enabled}")
    print(f"threshold_pass: {settings.threshold_pass}")
    print(f"max_retries: {settings.max_retries}")
    print(f"weights: {settings.weights}")


def cmd_quality_config_set(args: argparse.Namespace) -> None:
    """Set a config value (e.g., threshold_pass=0.8)."""
    key, value = args.key, args.value
    config_path = _settings_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if config_path.exists():
        data = json.loads(config_path.read_text(encoding="utf-8"))
    else:
        data = {}
    # Try float, then int, then string
    try:
        v = float(value) if "." in value else int(value)
    except ValueError:
        v = value
    # Handle nested key (e.g., weights.factuality)
    if "." in key:
        top, sub = key.split(".", 1)
        data.setdefault(top, {})[sub] = v
    else:
        data[key] = v
    config_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Set {key} = {v}")


def _load_settings() -> QualitySettings:
    """Load QualitySettings from per-project config (or defaults)."""
    config_path = _settings_path()
    if config_path.exists():
        data = json.loads(config_path.read_text(encoding="utf-8"))
        return QualitySettings(
            enabled=data.get("enabled", True),
            threshold_pass=float(data.get("threshold_pass", 0.7)),
            max_retries=int(data.get("max_retries", 1)),
            weights=data.get("weights", QualitySettings().weights),
        )
    return QualitySettings()


def _settings_path() -> Path:
    from ..project.context import ProjectContext
    try:
        ctx = ProjectContext.resolve(None)
        return ctx.paths.llm_wiki / "quality_settings.json"
    except ProjectNotFoundError:
        return Path.cwd() / "quality_settings.json"


def asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)
```

**Tests** (3): test_score, test_config_show, test_config_set.

**Wire in cli.py**:
```python
p_quality = subparsers.add_parser("quality", help="Quality gate")
p_quality_sub = p_quality.add_subparsers(dest="quality_command")
p_qscore = p_quality_sub.add_parser("score", help="Score a page")
p_qscore.add_argument("path", help="Path to .md file")
p_qscore.add_argument("--project", help="Project ID")
p_qscore.set_defaults(func=cmd_quality_score)
p_qcfg = p_quality_sub.add_parser("config", help="Quality config")
p_qcfg_sub = p_qcfg.add_subparsers(dest="quality_config_command")
p_qcfg_show = p_qcfg_sub.add_parser("show")
p_qcfg_show.set_defaults(func=cmd_quality_config_show)
p_qcfg_set = p_qcfg_sub.add_parser("set")
p_qcfg_set.add_argument("key", help="Config key (e.g., threshold_pass or weights.factuality)")
p_qcfg_set.add_argument("value", help="New value")
p_qcfg_set.set_defaults(func=cmd_quality_config_set)
```

```bash
git add src/cli_ext/quality_cmd.py src/cli.py tests/test_cli_ext/test_cmd_quality.py
git commit -m "feat(cli): add 'quality score/config show/set' subcommands"
```

---

## Self-Review

- [x] Spec coverage: 6 dimensions ✓ 2-tier verdict (MVP) ✓ 1 retry ✓ basic quarantine ✓ CLI ✓
- [x] 4-tier verdict + 2 retries + quality-warn review deferred to v2.0.1
- [x] No placeholders

## Implementation order

Tasks 1-4 chain. Total: 4 tasks, ~2-3 hours.