"""Plan 4 — V7 cost observability: CostLedger + price env."""
from src.lib.budget import CostLedger, load_default_prices


def test_record_accumulates_tokens_and_cost():
    ledger = CostLedger()
    ledger.record(stage="classify", input_tokens=100, output_tokens=50,
                  input_price=0.0000003, output_price=0.0000006)
    assert ledger.input_tokens == 100
    assert ledger.output_tokens == 50
    assert ledger.cost_usd == round(100*0.0000003 + 50*0.0000006, 6)
    assert ledger.call_count == 1
    assert ledger.cost_by_stage["classify"]["input_tokens"] == 100


def test_record_multiple_stages_separately():
    ledger = CostLedger()
    ledger.record(stage="classify", input_tokens=100, output_tokens=50,
                  input_price=0.0000003, output_price=0.0000006)
    ledger.record(stage="cluster", input_tokens=200, output_tokens=80,
                  input_price=0.0000003, output_price=0.0000006)
    assert ledger.call_count == 2
    assert ledger.cost_by_stage["classify"]["calls"] == 1
    assert ledger.cost_by_stage["cluster"]["calls"] == 1


def test_snapshot_returns_full_breakdown():
    ledger = CostLedger()
    ledger.record(stage="classify", input_tokens=100, output_tokens=50,
                  input_price=0.0000003, output_price=0.0000006)
    snap = ledger.snapshot()
    assert "cumulative_usd" in snap
    assert "cost_by_stage" in snap
    assert "cost_per_call_avg" in snap
    assert snap["call_count"] == 1
    assert snap["cumulative_usd"] > 0


def test_load_default_prices_uses_env_overrides(monkeypatch):
    monkeypatch.setenv("RUFLO_INPUT_TOKEN_PRICE", "0.5")
    monkeypatch.setenv("RUFLO_OUTPUT_TOKEN_PRICE", "1.5")
    in_p, out_p = load_default_prices()
    assert in_p == 0.5
    assert out_p == 1.5


def test_load_default_prices_falls_back_to_defaults_on_missing_or_invalid(monkeypatch):
    monkeypatch.delenv("RUFLO_INPUT_TOKEN_PRICE", raising=False)
    monkeypatch.delenv("RUFLO_OUTPUT_TOKEN_PRICE", raising=False)
    in_p, out_p = load_default_prices()
    assert in_p == 0.0000003
    assert out_p == 0.0000006

    monkeypatch.setenv("RUFLO_INPUT_TOKEN_PRICE", "free")
    monkeypatch.setenv("RUFLO_OUTPUT_TOKEN_PRICE", "")
    in_p, out_p = load_default_prices()
    assert in_p == 0.0000003
    assert out_p == 0.0000006
