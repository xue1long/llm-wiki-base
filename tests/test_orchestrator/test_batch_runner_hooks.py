from src.orchestrator import batch_runner
from src.orchestrator.batch_runner_internal import hooks
from src.orchestrator.batch_runner_internal import gate, state
from src.orchestrator.batch_runner_internal import phases
from src.orchestrator.batch_runner_internal import raw_lifecycle


def test_batch_runner_facade_reexports_hooks():
    for name in (
        "_crash_at",
        "_snapshot_page_hashes",
        "_fake_generate",
        "_is_fake_mode",
        "_estimate_batch_cost",
        "_resolve_paths",
        "_resolve_provider",
    ):
        assert getattr(batch_runner, name) is getattr(hooks, name)


def test_fake_mode_and_cost_remain_compatible(monkeypatch):
    monkeypatch.setenv("RUFLO_EXECUTOR_FAKE_GENERATE", "1")
    monkeypatch.setenv("RUFLO_FAKE_COST", "0.7")
    assert batch_runner._is_fake_mode() is True
    assert batch_runner._estimate_batch_cost(2, 1) == 0.7


def test_batch_runner_facade_reexports_raw_lifecycle():
    for name in (
        "_git_snapshot",
        "_is_immutable_source",
        "_generate_raw",
        "_commit_raw",
        "_upsert_batch_vectors",
        "_ensure_rebuild_clean",
        "_clear_stale_vectors",
        "_commit_ingest",
    ):
        assert getattr(batch_runner, name) is getattr(raw_lifecycle, name)


def test_batch_runner_facade_reexports_gate_and_state_helpers():
    for name in ("_rerun_gate_batch", "Batch", "GateReport"):
        assert getattr(batch_runner, name) is getattr(gate, name)
    for name in ("_set_batch_status", "_update_fail_streak", "MAX_FAIL_STREAK"):
        assert getattr(batch_runner, name) is getattr(state, name)


def test_batch_runner_facade_reexports_phase_helpers():
    assert batch_runner._phase_generate is phases._phase_generate
    assert batch_runner._phase_gate is phases._phase_gate
    assert batch_runner._phase_recheck_and_finalize is phases._phase_recheck_and_finalize
    assert batch_runner._phase_commit is phases._phase_commit
    assert batch_runner._prepare_batch is phases._prepare_batch
