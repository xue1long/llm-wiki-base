"""Tests for EvolutionScheduler — lightweight periodic evolution trigger."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.knowledge.evolution.loop import EvolutionResult
from src.knowledge.evolution.scheduler import EvolutionScheduler
from src.wiki.core.paths import WikiPaths


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def wiki_paths(tmp_path: Path) -> WikiPaths:
    """WikiPaths pointing at a temp directory."""
    return WikiPaths(root=tmp_path)


@pytest.fixture
def mock_loop() -> MagicMock:
    """EvolutionLoop mock whose run() returns an EvolutionResult."""
    loop = MagicMock()
    loop.run = AsyncMock(return_value=EvolutionResult(
        run_at=0,
        proposals_generated=3,
        proposals_approved=2,
        proposals_applied=0,
        proposals_rejected=0,
        proposals_skipped=1,
        errors=[],
        duration_ms=42,
    ))
    return loop


@pytest.fixture
def state_file(wiki_paths: WikiPaths) -> Path:
    """Path to the scheduler state file."""
    return wiki_paths.index / "curator_last_run.json"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    """Class-level constants are set correctly."""

    def test_min_run_interval_is_23_hours(self):
        assert EvolutionScheduler.MIN_RUN_INTERVAL_SECONDS == 82800

    def test_check_interval_is_one_hour(self):
        assert EvolutionScheduler.CHECK_INTERVAL_SECONDS == 3600


# ---------------------------------------------------------------------------
# Tests: last_run_at
# ---------------------------------------------------------------------------


class TestLastRunAtNew:
    """No state file → last_run_at returns 0."""

    def test_no_file_returns_zero(self, wiki_paths: WikiPaths, mock_loop: MagicMock):
        scheduler = EvolutionScheduler(mock_loop, wiki_paths)
        assert scheduler.last_run_at == 0


# ---------------------------------------------------------------------------
# Tests: _should_run
# ---------------------------------------------------------------------------


class TestShouldRunFirstTime:
    """Never run → should_run returns True."""

    def test_first_run_returns_true(self, wiki_paths: WikiPaths, mock_loop: MagicMock):
        scheduler = EvolutionScheduler(mock_loop, wiki_paths)
        assert scheduler._should_run() is True


class TestShouldRunRecent:
    """Recently run → should_run returns False."""

    def test_recent_run_returns_false(
        self, wiki_paths: WikiPaths, mock_loop: MagicMock, monkeypatch
    ):
        base_sec = 1_700_000_000.0
        # Simulate a run recorded 1 hour ago
        state_file = wiki_paths.index / "curator_last_run.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(
            json.dumps({"last_run_at": int(base_sec * 1000), "run_count": 1})
        )

        monkeypatch.setattr(time, "time", lambda: base_sec + 3600)

        scheduler = EvolutionScheduler(mock_loop, wiki_paths)
        assert scheduler._should_run() is False


class TestShouldRunOld:
    """Last run was 24h ago → should_run returns True."""

    def test_old_run_returns_true(
        self, wiki_paths: WikiPaths, mock_loop: MagicMock, monkeypatch
    ):
        base_sec = 1_700_000_000.0
        state_file = wiki_paths.index / "curator_last_run.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(
            json.dumps({"last_run_at": int(base_sec * 1000), "run_count": 1})
        )

        monkeypatch.setattr(time, "time", lambda: base_sec + 86400)

        scheduler = EvolutionScheduler(mock_loop, wiki_paths)
        assert scheduler._should_run() is True


# ---------------------------------------------------------------------------
# Tests: _record_run
# ---------------------------------------------------------------------------


class TestRecordRunUpdatesState:
    """_record_run writes timestamp and increments count."""

    def test_record_run_writes_state_file(
        self, wiki_paths: WikiPaths, mock_loop: MagicMock, monkeypatch
    ):
        fixed_ms = 1_700_000_000_000
        monkeypatch.setattr(time, "time", lambda: fixed_ms)

        scheduler = EvolutionScheduler(mock_loop, wiki_paths)
        scheduler._record_run()

        state_file = wiki_paths.index / "curator_last_run.json"
        assert state_file.exists()
        data = json.loads(state_file.read_text(encoding="utf-8"))
        assert data["last_run_at"] == fixed_ms * 1000
        assert data["run_count"] == 1

    def test_record_run_updates_last_run_at(
        self, wiki_paths: WikiPaths, mock_loop: MagicMock, monkeypatch
    ):
        fixed_sec = 1_700_000_000
        monkeypatch.setattr(time, "time", lambda: fixed_sec)

        scheduler = EvolutionScheduler(mock_loop, wiki_paths)
        scheduler._record_run()

        assert scheduler.last_run_at == int(fixed_sec * 1000)


class TestRecordRunIncrements:
    """Two _record_run calls → run_count=2."""

    def test_two_runs_increments_run_count(
        self, wiki_paths: WikiPaths, mock_loop: MagicMock, monkeypatch
    ):
        monkeypatch.setattr(time, "time", lambda: 1_700_000_000)

        scheduler = EvolutionScheduler(mock_loop, wiki_paths)
        scheduler._record_run()
        scheduler._record_run()

        assert scheduler.run_count == 2

    def test_run_count_reads_from_disk(
        self, wiki_paths: WikiPaths, mock_loop: MagicMock
    ):
        state_file = wiki_paths.index / "curator_last_run.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(
            json.dumps({"last_run_at": 1_700_000_000_000, "run_count": 5})
        )

        scheduler = EvolutionScheduler(mock_loop, wiki_paths)
        assert scheduler.run_count == 5


# ---------------------------------------------------------------------------
# Tests: trigger_now
# ---------------------------------------------------------------------------


class TestTriggerNow:
    """trigger_now runs evolution cycle immediately."""

    @pytest.mark.asyncio
    async def test_trigger_now_returns_result(
        self, wiki_paths: WikiPaths, mock_loop: MagicMock
    ):
        scheduler = EvolutionScheduler(mock_loop, wiki_paths)
        result = await scheduler.trigger_now()

        assert isinstance(result, EvolutionResult)
        assert result.proposals_generated == 3
        assert result.proposals_approved == 2
        assert result.proposals_skipped == 1

    @pytest.mark.asyncio
    async def test_trigger_now_calls_loop_run(
        self, wiki_paths: WikiPaths, mock_loop: MagicMock
    ):
        scheduler = EvolutionScheduler(mock_loop, wiki_paths)
        await scheduler.trigger_now()

        mock_loop.run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_trigger_now_records_run(
        self, wiki_paths: WikiPaths, mock_loop: MagicMock, monkeypatch
    ):
        fixed_sec = 1_700_000_000
        monkeypatch.setattr(time, "time", lambda: fixed_sec)

        scheduler = EvolutionScheduler(mock_loop, wiki_paths)
        await scheduler.trigger_now()

        assert scheduler.last_run_at == int(fixed_sec * 1000)
        assert scheduler.run_count == 1


# ---------------------------------------------------------------------------
# Tests: start / stop lifecycle
# ---------------------------------------------------------------------------


class TestStartStopLifecycle:
    """start() → is_running=True, stop() → is_running=False."""

    @pytest.mark.asyncio
    async def test_start_sets_running(
        self, wiki_paths: WikiPaths, mock_loop: MagicMock
    ):
        scheduler = EvolutionScheduler(mock_loop, wiki_paths)
        assert scheduler.is_running is False

        await scheduler.start()
        assert scheduler.is_running is True

        # Cleanup
        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_stop_clears_running(
        self, wiki_paths: WikiPaths, mock_loop: MagicMock
    ):
        scheduler = EvolutionScheduler(mock_loop, wiki_paths)
        await scheduler.start()
        assert scheduler.is_running is True

        await scheduler.stop()
        assert scheduler.is_running is False

    @pytest.mark.asyncio
    async def test_start_twice_is_noop(
        self, wiki_paths: WikiPaths, mock_loop: MagicMock
    ):
        scheduler = EvolutionScheduler(mock_loop, wiki_paths)
        await scheduler.start()
        task1 = scheduler._task

        await scheduler.start()
        task2 = scheduler._task

        # Same task, no duplicate
        assert task1 is task2
        assert scheduler.is_running is True

        # Cleanup
        await scheduler.stop()


# ---------------------------------------------------------------------------
# Tests: state file persistence
# ---------------------------------------------------------------------------


class TestStateFilePersistence:
    """State survives scheduler rebuild — reads from JSON on disk."""

    def test_new_scheduler_reads_existing_state(
        self, wiki_paths: WikiPaths, mock_loop: MagicMock, monkeypatch
    ):
        fixed_sec = 1_700_000_000
        monkeypatch.setattr(time, "time", lambda: fixed_sec)

        # Create and record
        scheduler1 = EvolutionScheduler(mock_loop, wiki_paths)
        scheduler1._record_run()

        # Build a second scheduler against the same paths
        mock_loop2 = MagicMock()
        scheduler2 = EvolutionScheduler(mock_loop2, wiki_paths)

        assert scheduler2.last_run_at == int(fixed_sec * 1000)
        assert scheduler2.run_count == 1


# ---------------------------------------------------------------------------
# Tests: error resilience
# ---------------------------------------------------------------------------


class TestSchedulerLoopErrorResilience:
    """When EvolutionLoop.run() raises, the scheduler logs and continues."""

    @pytest.mark.asyncio
    async def test_loop_run_error_does_not_crash_scheduler(
        self, wiki_paths: WikiPaths, monkeypatch
    ):
        mock_loop = MagicMock()
        mock_loop.run = AsyncMock(side_effect=RuntimeError("boom"))

        scheduler = EvolutionScheduler(mock_loop, wiki_paths)
        scheduler._running = True  # Must be True for the while-loop to enter

        # Mock sleep to exit after one iteration (otherwise the loop runs forever)
        sleep_counts = []

        async def short_sleep(seconds):
            sleep_counts.append(1)
            if len(sleep_counts) >= 2:
                scheduler._running = False

        monkeypatch.setattr(asyncio, "sleep", short_sleep)

        # Run the scheduler loop directly — must not raise
        await scheduler._scheduler_loop()

        # Evolution loop was called (error caught and logged, not propagated)
        assert mock_loop.run.called

    @pytest.mark.asyncio
    async def test_scheduler_still_running_after_error(
        self, wiki_paths: WikiPaths, monkeypatch
    ):
        mock_loop = MagicMock()
        mock_loop.run = AsyncMock(side_effect=RuntimeError("boom"))

        scheduler = EvolutionScheduler(mock_loop, wiki_paths)

        await scheduler.start()
        # is_running should be True even though the loop has an error
        assert scheduler.is_running is True

        await scheduler.stop()
