"""Gold corpus framework for V7 pipeline regression (Task 46, Commit 1).

Each V7 stage is a regression surface that may silently break across
prompt changes / refactors. Gold corpus is the safety net: a
``tests/corpus/v7_gold/<stage>_<n>.json`` directory of small fixtures
(input + expected output), run by ``CorpusRunner`` to verify the stage
behaves correctly end-to-end.

This commit ships the framework + Stage 1 (classify) corpus. Other
stages (segment / completeness / cluster / fill / write / 6R /
reconciliation) are added incrementally as separate commits.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Sequence

from src.pipeline.v7_extract.llm_client import LLMClient


log = logging.getLogger(__name__)


# Default corpus root (relative to repo root).
DEFAULT_CORPUS_ROOT = Path("tests/corpus/v7_gold")


@dataclass
class CorpusFixture:
    id: str
    stage: str
    description: str
    input: dict[str, Any]
    expected: dict[str, Any]


@dataclass
class CorpusRunResult:
    fixture_id: str
    stage: str
    passed: bool
    diff: str = ""


class CorpusLoader:
    """Discover and parse JSON fixtures under a root directory."""

    @staticmethod
    def discover(root: Path | str = DEFAULT_CORPUS_ROOT) -> list[Path]:
        root_path = Path(root)
        if not root_path.exists():
            return []
        return sorted(p for p in root_path.rglob("*.json") if p.is_file())

    @staticmethod
    def load(path: Path) -> CorpusFixture | None:
        """Parse a single fixture file. None on missing required fields."""
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as e:
            log.warning("CorpusLoader: cannot read %s: %s", path, e)
            return None
        try:
            payload = json.loads(text)
        except ValueError as e:
            log.warning("CorpusLoader: %s is not valid JSON: %s", path, e)
            return None
        if not isinstance(payload, dict):
            return None
        required = ("id", "stage", "description", "input", "expected")
        for key in required:
            if key not in payload:
                log.warning("CorpusLoader: %s missing field %r", path, key)
                return None
        return CorpusFixture(
            id=str(payload["id"]),
            stage=str(payload["stage"]),
            description=str(payload["description"]),
            input=dict(payload["input"]),
            expected=dict(payload["expected"]),
        )


# ---------------------------------------------------------------------------
# Stage-specific runners
# ---------------------------------------------------------------------------


def _diff_strings(expected: Any, actual: Any, *, indent: int = 0) -> str:
    """Render a short diff between expected and actual values."""
    pad = "  " * indent
    if expected == actual:
        return ""
    e = repr(expected)
    a = repr(actual)
    return f"{pad}expected: {e}\n{pad}actual:   {a}"


async def run_stage1(
    fixture: CorpusFixture,
    *,
    llm: LLMClient,
) -> CorpusRunResult:
    """Run Stage 1 (classify_doc) and compare to expected.

    Expected fields supported:
      - doc_type: str (one of the 6 valid doc_types)
      - failed: bool
      - traits_subset: list[str] (subset check; actual may be a superset)
      - min_confidence: float

    If ``fixture.input.llm_response`` is set, the runner first ensures
    the LLM returns that response (no-op if it's a FakeLLMClient; real
    clients will be called normally).
    """
    from src.pipeline.v7_extract.doc_classifier import classify_doc
    from src.pipeline.v7_extract.llm_client import FakeLLMClient

    content = str(fixture.input.get("content", ""))
    filename_hint = str(fixture.input.get("filename_hint", ""))
    active_llm: LLMClient = llm
    llm_response = fixture.input.get("llm_response")
    if llm_response is not None and isinstance(active_llm, FakeLLMClient):
        # Queue a scripted response for the next call. If the runner
        # was given a different llm, leave it alone.
        active_llm = FakeLLMClient()
        active_llm.script(
            "classify",
            json.dumps(llm_response, ensure_ascii=False),
        )

    result = await classify_doc(
        content, filename_hint=filename_hint, llm=active_llm, project_root=None,
    )
    diffs: list[str] = []
    if "doc_type" in fixture.expected:
        if result.doc_type != fixture.expected["doc_type"]:
            diffs.append(_diff_strings(
                fixture.expected["doc_type"], result.doc_type, indent=1,
            ))
    if "failed" in fixture.expected:
        if result.failed != fixture.expected["failed"]:
            diffs.append(_diff_strings(
                fixture.expected["failed"], result.failed, indent=1,
            ))
    if "traits_subset" in fixture.expected:
        expected_traits = set(fixture.expected["traits_subset"])
        actual_traits = set(result.traits or [])
        if not expected_traits.issubset(actual_traits):
            diffs.append(
                f"  expected traits superset {sorted(expected_traits)}; "
                f"actual traits = {sorted(actual_traits)}"
            )
    if "min_confidence" in fixture.expected:
        min_c = float(fixture.expected["min_confidence"])
        if result.confidence < min_c:
            diffs.append(
                f"  expected confidence >= {min_c}; got {result.confidence:.3f}"
            )
    return CorpusRunResult(
        fixture_id=fixture.id,
        stage=fixture.stage,
        passed=not diffs,
        diff="\n".join(diffs),
    )


# Per-stage dispatcher. New stages add their runner here.
STAGE_RUNNERS: dict[str, Callable[..., Awaitable[CorpusRunResult]]] = {
    "stage1_classify": run_stage1,
}


class CorpusRunner:
    """Run a set of fixtures through their stage-specific runners.

    Use ``run(fixtures)`` to execute all (or ``run_stage(stage)`` for
    a subset). The runner returns per-fixture ``CorpusRunResult`` so
    tests can assert pass/fail and surface a useful diff on failure.
    """

    def __init__(self, *, llm: LLMClient) -> None:
        self.llm = llm

    def run(self, fixtures: Sequence[CorpusFixture]) -> list[CorpusRunResult]:
        return self._run_sync(fixtures)

    def _run_sync(self, fixtures: Sequence[CorpusFixture]) -> list[CorpusRunResult]:
        import asyncio
        results: list[CorpusRunResult] = []
        for fx in fixtures:
            runner = STAGE_RUNNERS.get(fx.stage)
            if runner is None:
                results.append(CorpusRunResult(
                    fixture_id=fx.id, stage=fx.stage, passed=False,
                    diff=f"no runner registered for stage {fx.stage!r}",
                ))
                continue
            try:
                result = asyncio.run(runner(fx, llm=self.llm))
            except Exception as e:  # noqa: BLE001
                results.append(CorpusRunResult(
                    fixture_id=fx.id, stage=fx.stage, passed=False,
                    diff=f"runner raised: {type(e).__name__}: {e}",
                ))
                continue
            results.append(result)
        return results

    def run_stage(self, stage: str) -> list[CorpusRunResult]:
        all_fixtures = [
            CorpusLoader.load(p) for p in CorpusLoader.discover()
            if True
        ]
        stage_fixtures = [f for f in all_fixtures if f is not None and f.stage == stage]
        return self.run(stage_fixtures)


__all__ = [
    "CorpusFixture",
    "CorpusLoader",
    "CorpusRunResult",
    "CorpusRunner",
    "DEFAULT_CORPUS_ROOT",
    "STAGE_RUNNERS",
]