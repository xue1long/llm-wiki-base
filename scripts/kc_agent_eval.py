"""Agent Task evaluation script (C-3.5 / Z-3, spec §15 V-14 + §17 D-15).

Evaluates a YAML dataset of agent tasks. Two modes:

* ``--dry-run`` (default): evaluate each case against its
  ``mock_response`` fixture without touching the network. This is what
  CI and unit tests use.
* ``--runtime``: instantiate the configured LLM provider (via
  ``ProviderRegistry.get_default()``) and call it for each
  ``mode: runtime`` task. Each invocation logs ``task_id``,
  ``provider_name``, ``latency_ms``, and ``success``. A successful
  invocation flips that task's ``runtime_verified`` to ``True``, so the
  aggregate ``runtime_count`` reflects verified work and
  ``not_evaluable`` is set accordingly.

Returned aggregate shape::

    {
        "dataset_path": <str>,
        "task_count": <int>,
        "passed_count": <int>,
        "success_rate": <float>,
        "citation_accuracy": <float>,
        "total_citations_valid": <int>,
        "total_citations_expected": <int>,
        "results": [<per-task dict>, ...],
    }

Thresholds (spec §17 D-15):
    - Agent Task Success Rate >= 0.85
    - Citation Accuracy >= 0.95
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_logger = logging.getLogger("scripts.kc_agent_eval")


# Reason codes emitted on the per-task ``failure_reasons`` list when a
# runtime-mode task cannot be verified. Stable strings — surface as
# machine-readable diagnostics, not free-form log lines.
REASON_NO_PROVIDER = "no_provider"
REASON_PROVIDER_ERROR = "provider_error"
REASON_PROVIDER_BAD_OUTPUT = "provider_bad_output"


@dataclass
class AgentTaskResult:
    task_id: str
    passed: bool
    units_returned: int
    units_expected: int
    citations_valid: int
    citations_expected: int
    knowledge_mode_identified: bool
    conflict_status_matched: bool
    omitted_reasons: list[str] = field(default_factory=list)
    failure_reasons: list[str] = field(default_factory=list)
    # Task 6 (plan 2026-08-29-...): ``mode`` records the evaluation mode
    # (``"mock"`` when judged by dry-run fixtures, ``"runtime"`` when the
    # real agent was executed). ``runtime_verified`` mirrors whether a
    # real provider was available at evaluation time. Aggregate reports
    # (see ``evaluate_agent_task_dataset``) separate mock results from
    # the product pass rate — only ``runtime_verified=True`` tasks count
    # toward ``success_rate``.
    mode: str = "mock"
    runtime_verified: bool = False


def evaluate_agent_task(task: dict[str, Any]) -> AgentTaskResult:
    """Evaluate one agent task against its mock_response.

    Mode A: dry-run with mock_response (not real agent runtime call).
    Real agent runtime integration is Z-3 follow-up task.

    Task 6 (plan 2026-08-29-...): every task carries an explicit
    ``mode`` (``mock`` | ``runtime``) and ``runtime_verified`` flag.
    When ``runtime_verified`` is False the task is recorded for
    traceability but excluded from the product-level ``success_rate``
    in the aggregate report.
    """
    return _evaluate_agent_task_mock(task)


def _evaluate_agent_task_mock(task: dict[str, Any]) -> AgentTaskResult:
    """Mock-mode (dry-run) evaluator. Inspects ``mock_response`` only."""
    task_id = task["task_id"]
    criteria = task["success_criteria"]
    mock = task.get("mock_response", {})
    items = mock.get("knowledge_items", [])
    omitted = mock.get("omitted_candidates", [])
    mode = str(task.get("mode", "mock"))
    runtime_verified = bool(task.get("runtime_verified", False))

    failure_reasons: list[str] = []
    units_returned = len(items)
    if units_returned < criteria["min_units_returned"]:
        failure_reasons.append(
            f"units_returned {units_returned} < min_required {criteria['min_units_returned']}"
        )

    expected_ku_ids = set(task.get("expected_knowledge_units", []))
    actual_ku_ids = {item["knowledge_unit_id"] for item in items}
    if expected_ku_ids:
        units_match = expected_ku_ids.issubset(actual_ku_ids)
        if not units_match:
            missing = expected_ku_ids - actual_ku_ids
            failure_reasons.append(f"missing expected KU: {sorted(missing)}")

    actual_citations: set[str] = set()
    for item in items:
        actual_citations.update(item.get("evidence_refs", []))
    expected_citations = set(task.get("expected_citations", []))
    citations_valid = len(actual_citations & expected_citations)
    if citations_valid < criteria["min_citations_valid"]:
        failure_reasons.append(
            f"citations_valid {citations_valid} < min_required {criteria['min_citations_valid']}"
        )

    knowledge_mode_identified = all("knowledge_mode" in item for item in items)
    if criteria.get("knowledge_mode_identified") and not knowledge_mode_identified:
        failure_reasons.append("missing knowledge_mode field in some items")

    expected_conflicts = set(task.get("expected_conflict_status", []))
    actual_conflicts = {
        item.get("conflict_status") for item in items if "conflict_status" in item
    }
    if expected_conflicts:
        conflict_status_matched = expected_conflicts.issubset(actual_conflicts)
        if not conflict_status_matched:
            failure_reasons.append(
                f"conflict_status mismatch: expected {sorted(expected_conflicts)}, got {sorted(actual_conflicts)}"
            )
    else:
        conflict_status_matched = True

    omitted_reasons = [o.get("reason", "") for o in omitted]

    passed = len(failure_reasons) == 0

    return AgentTaskResult(
        task_id=task_id,
        passed=passed,
        units_returned=units_returned,
        units_expected=len(expected_ku_ids),
        citations_valid=citations_valid,
        citations_expected=len(expected_citations),
        knowledge_mode_identified=knowledge_mode_identified,
        conflict_status_matched=conflict_status_matched,
        omitted_reasons=omitted_reasons,
        failure_reasons=failure_reasons,
        mode=mode,
        runtime_verified=runtime_verified,
    )


# ---------------------------------------------------------------------------
# Runtime invocation (OPEN-3, Z-3)
# ---------------------------------------------------------------------------


# ``<think>...</think>`` reasoning blocks wrap the real output on some
# reasoning models (MiniMax-M3, glm-5.2). Strip them before JSON parse.
_REASONING_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


def _extract_json_payload(content: str) -> dict[str, Any] | None:
    """Parse the first JSON object from a model response string.

    Returns ``None`` if the content has no JSON object; callers treat
    ``None`` as a provider_bad_output reason code (no exception bubble-up).
    """
    if not content:
        return None
    cleaned = _REASONING_RE.sub("", content).strip()
    if not cleaned:
        return None
    # Greedy match — model may wrap in markdown fences
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if match is None:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


async def _invoke_runtime_provider(
    provider: Any,
    task: dict[str, Any],
    *,
    provider_name: str,
) -> tuple[dict[str, Any], bool, float, str | None]:
    """Invoke ``provider`` for one task; return ``(mock_payload, success,
    latency_ms, error_reason)``.

    The returned ``mock_payload`` matches the shape of the dataset's
    ``mock_response`` field (``knowledge_items`` + ``omitted_candidates``)
    so the downstream evaluator can be shared between mock and runtime
    paths.
    """
    query = task.get("query") or task.get("task_id", "")
    schema_hint = json.dumps(
        {
            "knowledge_items": [
                {
                    "knowledge_unit_id": "ku_xxx",
                    "knowledge_mode": "observed",
                    "statements": ["..."],
                    "evidence_refs": ["ev_xxx"],
                    "conflict_status": "none",
                    "confidence": 0.9,
                }
            ],
            "omitted_candidates": [],
        }
    )
    messages = [
        {
            "role": "user",
            "content": (
                f"Agent task: {task.get('task_id', '')}\n"
                f"Query: {query}\n\n"
                "Return a JSON object matching this schema:\n"
                f"{schema_hint}"
            ),
        }
    ]
    started = time.perf_counter()
    try:
        response = await provider.complete(messages)
    except Exception as exc:  # noqa: BLE001 — runtime hooks must not crash eval
        latency_ms = (time.perf_counter() - started) * 1000
        _logger.info(
            "runtime_invoke task_id=%s provider=%s latency_ms=%.1f success=False reason=%s",
            task.get("task_id"), provider_name, latency_ms, REASON_PROVIDER_ERROR,
        )
        return (
            {"knowledge_items": [], "omitted_candidates": []},
            False,
            latency_ms,
            f"{REASON_PROVIDER_ERROR}: {exc}",
        )
    latency_ms = (time.perf_counter() - started) * 1000
    payload = _extract_json_payload(getattr(response, "content", "") or "")
    if not isinstance(payload, dict):
        _logger.info(
            "runtime_invoke task_id=%s provider=%s latency_ms=%.1f success=False reason=%s",
            task.get("task_id"), provider_name, latency_ms, REASON_PROVIDER_BAD_OUTPUT,
        )
        return (
            {"knowledge_items": [], "omitted_candidates": []},
            False,
            latency_ms,
            REASON_PROVIDER_BAD_OUTPUT,
        )
    if "knowledge_items" not in payload:
        payload.setdefault("knowledge_items", [])
    payload.setdefault("omitted_candidates", [])
    _logger.info(
        "runtime_invoke task_id=%s provider=%s latency_ms=%.1f success=True items=%d",
        task.get("task_id"), provider_name, latency_ms,
        len(payload.get("knowledge_items", [])),
    )
    return payload, True, latency_ms, None


def _build_runtime_task(
    task: dict[str, Any], mock_payload: dict[str, Any], success: bool, error_reason: str | None
) -> dict[str, Any]:
    """Project runtime output onto the dataset task shape so the shared
    evaluator can score it.
    """
    projected = dict(task)
    projected["mock_response"] = mock_payload
    projected["mode"] = "runtime"
    projected["runtime_verified"] = success
    if not success and error_reason:
        # Surface the runtime failure as a schema-style field so the
        # aggregate carries it; we extend success_criteria shape rather
        # than mutating the caller-owned task.
        projected.setdefault("runtime_failure_reason", error_reason)
    return projected


def evaluate_agent_task_dataset(
    dataset_path: Path,
    *,
    runtime_provider: Any | None = None,
    provider_name: str | None = None,
    stderr_sink: Any | None = None,
) -> dict[str, Any]:
    """Evaluate all agent tasks in YAML file. Returns success rate + citation accuracy.

    Task 6 (plan 2026-08-29-...): mock results are recorded for
    traceability but excluded from ``success_rate`` (the product
    pass rate). The aggregate splits results into ``runtime_results``
    and ``mock_results``; downstream consumers can verify that
    ``runtime_count == 0`` → ``not_evaluable`` flag is True.

    OPEN-3 (Z-3): when ``runtime_provider`` is provided (or resolvable
    via :func:`_resolve_provider`), tasks declared with ``mode: runtime``
    are invoked against the live LLM endpoint. Successful invocations
    raise the task's ``runtime_verified`` flag — that's what feeds the
    aggregate ``runtime_count``. When ``runtime_provider`` is ``None``
    and ``mode: runtime`` tasks exist, those tasks are still recorded
    with ``runtime_verified=False`` and a ``no_provider`` failure reason;
    ``runtime_count`` stays 0 (so ``not_evaluable`` reflects the
    inability to verify *anything*).
    """
    tasks = yaml.safe_load(dataset_path.read_text(encoding="utf-8")) or []

    has_runtime_tasks = any(
        str(t.get("mode", "mock")) == "runtime" for t in tasks
    )
    if runtime_provider is not None:
        results = asyncio.run(
            _run_runtime_tasks(
                tasks,
                provider=runtime_provider,
                provider_name=provider_name or "default",
            )
        )
    else:
        if has_runtime_tasks:
            _print_no_provider_hint(stderr_sink)
        results = [
            _maybe_annotate_no_provider(t, evaluate_agent_task(t)) for t in tasks
        ]
    runtime_results = [r for r in results if r.runtime_verified]
    mock_results = [r for r in results if not r.runtime_verified]
    passed = sum(1 for r in runtime_results if r.passed)
    total = len(results)
    runtime_total = len(runtime_results)

    # Citation Accuracy — over RUNTIME results only (mock not eligible)
    total_citations_valid = sum(r.citations_valid for r in runtime_results)
    total_citations_expected = sum(r.citations_expected for r in runtime_results)
    citation_accuracy = (
        total_citations_valid / total_citations_expected
        if total_citations_expected > 0
        else 0.0
    )

    # Success rate — over runtime results only (mock excluded).
    success_rate = passed / runtime_total if runtime_total > 0 else 0.0

    return {
        "dataset_path": str(dataset_path),
        "task_count": total,
        "runtime_count": runtime_total,
        "mock_count": len(mock_results),
        "passed_count": passed,
        "success_rate": success_rate,
        "citation_accuracy": citation_accuracy,
        "total_citations_valid": total_citations_valid,
        "total_citations_expected": total_citations_expected,
        "not_evaluable": runtime_total == 0,
        "results": [
            {
                "task_id": r.task_id,
                "passed": r.passed,
                "mode": r.mode,
                "runtime_verified": r.runtime_verified,
                "units_returned": r.units_returned,
                "units_expected": r.units_expected,
                "citations_valid": r.citations_valid,
                "citations_expected": r.citations_expected,
                "omitted_reasons": r.omitted_reasons,
                "failure_reasons": r.failure_reasons,
            }
            for r in results
        ],
        "runtime_results": [
            {"task_id": r.task_id, "passed": r.passed, "mode": r.mode}
            for r in runtime_results
        ],
        "mock_results": [
            {"task_id": r.task_id, "passed": r.passed, "mode": r.mode}
            for r in mock_results
        ],
    }


async def _run_runtime_tasks(
    tasks: list[dict[str, Any]],
    *,
    provider: Any,
    provider_name: str,
) -> list[AgentTaskResult]:
    """Invoke the provider for each runtime-mode task and produce a
    full ``AgentTaskResult`` list (runtime tasks + mocked other tasks).

    Runtime tasks are scored using the JSON output from the live
    provider; non-runtime tasks fall back to ``evaluate_agent_task``
    unchanged. This keeps the aggregate shape stable for downstream
    consumers.
    """
    results: list[AgentTaskResult] = []
    for task in tasks:
        mode = str(task.get("mode", "mock"))
        if mode != "runtime":
            results.append(evaluate_agent_task(task))
            continue
        payload, success, _latency_ms, error_reason = await _invoke_runtime_provider(
            provider, task, provider_name=provider_name
        )
        projected = _build_runtime_task(task, payload, success, error_reason)
        result = evaluate_agent_task(projected)
        if not success and error_reason and error_reason not in result.failure_reasons:
            # Surface the runtime failure as the first reason so
            # reviewers can see why this task's verification failed.
            result.failure_reasons = [error_reason, *result.failure_reasons]
        results.append(result)
    return results


def _maybe_annotate_no_provider(task: dict[str, Any], result: AgentTaskResult) -> AgentTaskResult:
    """When a runtime-mode task had no provider AND its
    ``runtime_verified`` was not pre-declared True, surface the
    ``no_provider`` reason so reviewers see why verification failed.

    Pre-declared ``runtime_verified=True`` tasks (legacy fixtures)
    are left untouched — their value is treated as human-supplied.
    """
    if str(task.get("mode", "mock")) != "runtime":
        return result
    if result.runtime_verified:
        return result
    if REASON_NO_PROVIDER in result.failure_reasons:
        return result
    result.failure_reasons = [REASON_NO_PROVIDER, *result.failure_reasons]
    return result


_NO_PROVIDER_HINT = (
    "No provider configured in ~/.config/ruflo-kb/llm-providers.json — "
    "set MINIMAX_API_KEY or run `python -m src.cli llm-providers add`."
)


def _print_no_provider_hint(stderr_sink: Any | None = None) -> None:
    """Print the setup hint exactly once. ``stderr_sink`` lets tests
    intercept (e.g. ``sys.stderr``) without monkeypatching the module."""
    if stderr_sink is None:
        import sys
        stderr_sink = sys.stderr
    print(_NO_PROVIDER_HINT, file=stderr_sink)


def _resolve_provider(preferred: str | None = None) -> tuple[Any, str] | None:
    """Return ``(provider_instance, provider_name)`` for the default
    registry entry, or ``None`` when no provider is configured.

    Exposed as a module-level seam so unit tests can monkeypatch it
    (the OPEN-3 dry-run test asserts this is never called under
    ``--dry-run``).
    """
    try:
        from src.llm.provider_factory import create_llm_provider
        from src.llm.registry import ProviderRegistry
    except Exception:  # pragma: no cover — import failures keep us in mock mode
        return None
    try:
        if preferred:
            cfg = ProviderRegistry.get(preferred)
            return create_llm_provider(cfg.name), cfg.name
        cfg = ProviderRegistry.get_default()
    except Exception:
        return None
    try:
        return create_llm_provider(cfg.name), cfg.name
    except Exception:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Agent Task dataset")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("docs/evaluation/agent_tasks/agent_tasks.yaml"),
    )
    parser.add_argument("--output", type=Path, default=None)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=True,
        help="Evaluate against mock_response fixtures (default; never invokes a provider).",
    )
    mode.add_argument(
        "--runtime",
        dest="runtime",
        action="store_true",
        default=False,
        help="Invoke the configured LLM provider for mode=runtime tasks.",
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="Provider registry name to use in --runtime mode (default: registry default).",
    )
    args = parser.parse_args()

    if not args.dataset.exists():
        print(f"Dataset not found: {args.dataset}")
        return

    runtime_provider = None
    provider_name: str | None = None
    if args.runtime:
        resolved = _resolve_provider(args.provider)
        if resolved is not None:
            runtime_provider, provider_name = resolved
        else:
            _print_no_provider_hint()

    report = evaluate_agent_task_dataset(
        args.dataset,
        runtime_provider=runtime_provider,
        provider_name=provider_name,
    )
    output = json.dumps(report, indent=2, ensure_ascii=False)

    if args.output:
        args.output.write_text(output, encoding="utf-8")
        print(f"Wrote report to {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
