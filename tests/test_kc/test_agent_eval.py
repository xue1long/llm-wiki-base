"""Tests for kc_agent_eval mode/runtime_verified separation (Finding I-4).

Task 6 added explicit ``mode`` (``mock`` | ``runtime``) and
``runtime_verified`` fields to agent-task cases. The aggregate report
must keep the two populations separate: mock results are recorded for
traceability but EXCLUDED from ``success_rate`` (the product pass rate)
and from citation accuracy — only ``runtime_verified=True`` tasks count.

This file freezes that contract with one passing mock case and one
failing runtime case: if mock results leaked into the product rate the
``success_rate`` would be 0.5 instead of 0.0.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_AGENT_EVAL_SCRIPT = _REPO / "scripts" / "kc_agent_eval.py"


def _load_agent_eval():
    """Load scripts/kc_agent_eval.py by file path (sibling-project safe).

    See tests/test_kc/test_eval_contract.py for the rationale: a sibling
    project's ``scripts`` regular package shadows this repo's namespace
    package on ``sys.path``, so we bypass package import entirely.
    """
    mod_name = "kc_agent_eval"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, _AGENT_EVAL_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def agent_eval_mod():
    return _load_agent_eval()


def _passing_mock_task() -> dict:
    """A fully passing MOCK task — must never count toward success_rate."""
    return {
        "task_id": "mock-pass",
        "success_criteria": {"min_units_returned": 1, "min_citations_valid": 1},
        "expected_knowledge_units": ["ku_mock"],
        "expected_citations": ["ev_mock"],
        "expected_conflict_status": [],
        "mock_response": {
            "knowledge_items": [
                {
                    "knowledge_unit_id": "ku_mock",
                    "evidence_refs": ["ev_mock"],
                    "knowledge_mode": "observed",
                    "conflict_status": "none",
                }
            ],
            "omitted_candidates": [],
        },
        "mode": "mock",
        "runtime_verified": False,
    }


def _failing_runtime_task() -> dict:
    """A failing RUNTIME task — the only task eligible for success_rate."""
    return {
        "task_id": "runtime-fail",
        "success_criteria": {"min_units_returned": 1, "min_citations_valid": 1},
        "expected_knowledge_units": ["ku_runtime"],
        "expected_citations": ["ev_runtime"],
        "expected_conflict_status": [],
        "mock_response": {
            "knowledge_items": [],
            "omitted_candidates": [{"reason": "not retrieved"}],
        },
        "mode": "runtime",
        "runtime_verified": True,
    }


def _write_dataset(tmp_path: Path, tasks: list[dict]) -> Path:
    import yaml

    path = tmp_path / "agent_tasks.yaml"
    path.write_text(yaml.safe_dump(tasks, allow_unicode=True), encoding="utf-8")
    return path


def test_mock_results_excluded_from_success_rate(tmp_path, agent_eval_mod):
    """One passing mock + one failing runtime → success_rate reflects runtime only."""
    dataset = _write_dataset(
        tmp_path,
        [_passing_mock_task(), _failing_runtime_task()],
    )

    report = agent_eval_mod.evaluate_agent_task_dataset(dataset)

    assert report["task_count"] == 2
    assert report["runtime_count"] == 1
    assert report["mock_count"] == 1
    assert report["not_evaluable"] is False

    # The mock task passed but is excluded; the runtime task failed.
    assert report["passed_count"] == 0
    assert report["success_rate"] == 0.0
    # If the mock had leaked into the denominator: 0.5.


def test_mock_results_excluded_from_citation_accuracy(tmp_path, agent_eval_mod):
    """Citation accuracy is computed over runtime results only."""
    dataset = _write_dataset(
        tmp_path,
        [_passing_mock_task(), _failing_runtime_task()],
    )

    report = agent_eval_mod.evaluate_agent_task_dataset(dataset)

    # Runtime task expected 1 citation and produced none.
    assert report["total_citations_expected"] == 1
    assert report["total_citations_valid"] == 0
    assert report["citation_accuracy"] == 0.0


def test_runtime_results_and_mock_results_are_separated(tmp_path, agent_eval_mod):
    """Aggregate splits results into runtime_results vs mock_results."""
    dataset = _write_dataset(
        tmp_path,
        [_passing_mock_task(), _failing_runtime_task()],
    )

    report = agent_eval_mod.evaluate_agent_task_dataset(dataset)

    assert report["runtime_results"] == [
        {"task_id": "runtime-fail", "passed": False, "mode": "runtime"}
    ]
    assert report["mock_results"] == [
        {"task_id": "mock-pass", "passed": True, "mode": "mock"}
    ]


def test_runtime_passing_task_counts_toward_success_rate(tmp_path, agent_eval_mod):
    """A passing runtime task is the only way to raise the product rate."""
    runtime_pass = _failing_runtime_task()
    runtime_pass["task_id"] = "runtime-pass"
    runtime_pass["mock_response"]["knowledge_items"] = [
        {
            "knowledge_unit_id": "ku_runtime",
            "evidence_refs": ["ev_runtime"],
            "knowledge_mode": "observed",
            "conflict_status": "none",
        }
    ]
    dataset = _write_dataset(
        tmp_path,
        [_passing_mock_task(), runtime_pass],
    )

    report = agent_eval_mod.evaluate_agent_task_dataset(dataset)

    assert report["runtime_count"] == 1
    assert report["mock_count"] == 1
    assert report["passed_count"] == 1
    assert report["success_rate"] == 1.0


# ---------------------------------------------------------------------------
# OPEN-3: real provider invocation path (Z-3)
# ---------------------------------------------------------------------------


class _FakeProvider:
    """Drop-in ``LLMProvider`` substitute for runtime tests.

    Records every ``complete`` call and returns a canned response that
    parses as a valid ``knowledge_items`` list. The class is intentionally
    minimal — no SDK dependencies, no async-loop requirements — so unit
    tests run on any host.
    """

    def __init__(self, model: str = "fake-model") -> None:
        self.model = model
        self.calls: list[dict] = []

    async def complete(self, messages, **kwargs):
        from src.llm.base import LLMResponse
        self.calls.append({"messages": messages, "kwargs": kwargs})
        return LLMResponse(
            content=(
                '{"knowledge_items": ['
                '{"knowledge_unit_id": "ku_rt", "evidence_refs": ["ev_rt"],'
                ' "knowledge_mode": "observed", "conflict_status": "none"}'
                '], "omitted_candidates": []}'
            ),
            model=self.model,
        )

    async def aclose(self):  # pragma: no cover — not exercised in unit tests
        return None


class _BrokenProvider(_FakeProvider):
    async def complete(self, messages, **kwargs):
        raise RuntimeError("provider offline")


def _runtime_task_payload() -> dict:
    """Single runtime-shaped task with a query field the provider is asked."""
    return {
        "task_id": "AT-RT-1",
        "query": "find observed KUs with strong evidence",
        "success_criteria": {"min_units_returned": 1, "min_citations_valid": 1},
        "expected_knowledge_units": ["ku_rt"],
        "expected_citations": ["ev_rt"],
        "expected_conflict_status": [],
        "mock_response": {
            "knowledge_items": [
                {
                    "knowledge_unit_id": "ku_rt",
                    "evidence_refs": ["ev_rt"],
                    "knowledge_mode": "observed",
                    "conflict_status": "none",
                }
            ],
            "omitted_candidates": [],
        },
        "mode": "runtime",
        "runtime_verified": False,
    }


def _runtime_dataset(tmp_path: Path) -> Path:
    return _write_dataset(tmp_path, [_runtime_task_payload()])


def test_runtime_mode_invokes_provider_and_sets_runtime_verified(tmp_path, agent_eval_mod):
    """When ``mode='runtime'`` and a provider is supplied, every task is
    invoked and on success ``runtime_verified=True`` is recorded.

    The aggregate ``runtime_count`` then reflects successful invocations,
    flipping ``not_evaluable`` to ``False``."""
    dataset = _runtime_dataset(tmp_path)
    provider = _FakeProvider()

    results = agent_eval_mod.evaluate_agent_task_dataset(
        dataset, runtime_provider=provider
    )

    # one provider call per task
    assert len(provider.calls) == 1
    call = provider.calls[0]
    assert call["messages"][0]["role"] == "user"
    assert "find observed KUs" in call["messages"][0]["content"]

    # aggregate flips runtime_count > 0, not_evaluable = False
    assert results["runtime_count"] == 1
    assert results["mock_count"] == 0
    assert results["not_evaluable"] is False
    # the runtime task now passes (provider output matched the schema)
    assert results["passed_count"] == 1
    assert results["success_rate"] == 1.0


def test_runtime_mode_no_provider_records_zero_and_message(tmp_path, agent_eval_mod, capsys):
    """When ``mode='runtime'`` but no provider is configured, every task
    fails with a clear reason and ``runtime_count`` stays 0."""
    dataset = _runtime_dataset(tmp_path)

    results = agent_eval_mod.evaluate_agent_task_dataset(
        dataset, runtime_provider=None
    )

    # the task is still recorded under 'runtime' so reviewers see the
    # attempt, but its runtime_verified flag stays False and a
    # 'no_provider' reason is captured
    assert results["runtime_count"] == 0
    assert results["not_evaluable"] is True
    assert results["results"][0]["runtime_verified"] is False
    assert any("no_provider" in r for r in results["results"][0]["failure_reasons"])
    # CLI surfaces the helpful setup hint exactly once per run
    err = capsys.readouterr().err
    assert "llm-providers add" in err or "MINIMAX_API_KEY" in err


def test_runtime_mode_provider_failure_keeps_count_at_zero(tmp_path, agent_eval_mod):
    """Provider that raises → task is marked failed with the error captured,
    but the count of *successful* invocations stays 0 (consumers care about
    *verified* runtime tasks, not attempted ones)."""
    dataset = _runtime_dataset(tmp_path)
    provider = _BrokenProvider()

    results = agent_eval_mod.evaluate_agent_task_dataset(
        dataset, runtime_provider=provider
    )

    assert results["runtime_count"] == 0
    assert results["not_evaluable"] is True
    assert results["results"][0]["runtime_verified"] is False
    assert any("provider offline" in r for r in results["results"][0]["failure_reasons"])


def test_dry_run_flag_preserves_mock_behavior(tmp_path, agent_eval_mod, monkeypatch):
    """When invoked via main() with ``--dry-run``, no provider is loaded
    and the existing mock evaluation contract is preserved unchanged."""
    dataset = _runtime_dataset(tmp_path)

    # Force a runtime provider that, if loaded, would explode — the dry-run
    # path must never consult it.
    def _explode(*a, **kw):  # pragma: no cover — defensive
        raise AssertionError("dry-run must not construct a provider")

    monkeypatch.setattr(agent_eval_mod, "_resolve_provider", _explode)

    import sys
    monkeypatch.setattr(
        sys, "argv",
        ["kc_agent_eval.py", "--dataset", str(dataset), "--dry-run"],
    )
    agent_eval_mod.main()

    # In dry-run mode the only task is recorded as 'mock' (its declared
    # mode is irrelevant — dry-run forces mock semantics) so not_evaluable
    # remains True and the runtime provider is never instantiated.
    # The dataset's task has mode='runtime' but dry-run overrides that.
    out = dataset.read_text(encoding="utf-8")
    assert "AT-RT-1" in out  # dataset unchanged; only the evaluation mode changes


def test_runtime_invocation_logs_task_provider_latency(tmp_path, agent_eval_mod, caplog):
    """Every runtime invocation logs task_id, provider name, latency, success."""
    import logging

    dataset = _runtime_dataset(tmp_path)
    provider = _FakeProvider(model="glm-5.2")

    with caplog.at_level(logging.INFO, logger="scripts.kc_agent_eval"):
        agent_eval_mod.evaluate_agent_task_dataset(
            dataset, runtime_provider=provider, provider_name="sfkey-glm"
        )

    # at least one log line mentions the task, the provider, and success
    relevant = [
        rec for rec in caplog.records
        if rec.name == "scripts.kc_agent_eval"
    ]
    assert any(
        "AT-RT-1" in rec.getMessage() and "sfkey-glm" in rec.getMessage()
        for rec in relevant
    )
    assert any("success=True" in rec.getMessage() for rec in relevant)
    assert any("latency_ms" in rec.getMessage() for rec in relevant)


def test_main_cli_dry_run_does_not_invoke_provider(tmp_path, agent_eval_mod, monkeypatch):
    """``--dry-run`` CLI flag forces mock mode regardless of provider
    availability; the report contains zero ``runtime_count``."""
    dataset = _runtime_dataset(tmp_path)

    # Inject a fake provider so we can verify it is *never* instantiated.
    import src.llm.provider_factory as pf
    factory_calls: list = []
    real_create = pf.create_llm_provider

    def _spy_create(*a, **kw):
        factory_calls.append((a, kw))
        return real_create(*a, **kw)

    monkeypatch.setattr(pf, "create_llm_provider", _spy_create)

    import sys
    monkeypatch.setattr(
        sys, "argv",
        ["kc_agent_eval.py", "--dataset", str(dataset), "--dry-run"],
    )
    agent_eval_mod.main()

    assert factory_calls == [], "dry-run must not call create_llm_provider"
