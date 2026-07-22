"""Tests for `metrics` CLI subcommands."""
import json

from src.cli_ext.metrics_cmd import (
    cmd_metrics_show, cmd_metrics_reset, cmd_metrics_export, cmd_metrics_cost,
)
from src.metrics import MetricsRegistry, LLM_COST_USD_TOTAL


def setup_function(_):
    MetricsRegistry.reset_values()


def test_metrics_show_prints_text_format(capsys):
    MetricsRegistry.reset_values()
    LLM_COST_USD_TOTAL.inc(amount=0.5, provider="openai", model="gpt-4o-mini")
    cmd_metrics_show(type("A", (), {})())
    out = capsys.readouterr().out
    assert "# HELP ruflo_llm_cost_usd_total" in out
    assert "openai" in out


def test_metrics_reset_clears_state(capsys):
    MetricsRegistry.reset_values()
    LLM_COST_USD_TOTAL.inc(amount=2, provider="openai", model="x")
    cmd_metrics_reset(type("A", (), {})())
    out = capsys.readouterr().out
    assert "reset" in out.lower()
    # After reset, the value should be cleared.
    assert LLM_COST_USD_TOTAL.get(provider="openai", model="x") == 0


def test_metrics_export_writes_json(tmp_path):
    MetricsRegistry.reset_values()
    LLM_COST_USD_TOTAL.inc(amount=0.4, provider="anthropic", model="claude-haiku-4-5")
    out = tmp_path / "metrics.json"
    args = type("A", (), {"path": str(out)})()
    cmd_metrics_export(args)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data) >= 1
    # Find the LLM_COST_USD_TOTAL row (might be at any index in registry list)
    cost_rows = [r for r in data if r["name"] == "ruflo_llm_cost_usd_total"]
    assert len(cost_rows) == 1
    assert cost_rows[0]["labels"]["provider"] == "anthropic"
    assert cost_rows[0]["value"] == 0.4


def test_metrics_cost_sums_per_model(capsys):
    MetricsRegistry.reset_values()
    LLM_COST_USD_TOTAL.inc(amount=0.1, provider="openai", model="gpt-4o-mini")
    LLM_COST_USD_TOTAL.inc(amount=0.3, provider="anthropic", model="claude-haiku-4-5")
    cmd_metrics_cost(type("A", (), {})())
    out = capsys.readouterr().out
    assert "openai/gpt-4o-mini" in out
    assert "anthropic/claude-haiku-4-5" in out
    assert "Total: $0.40" in out
