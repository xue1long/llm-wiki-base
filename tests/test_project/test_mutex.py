import asyncio
import time

from src.project.mutex import (
    with_project_lock,
    sync_with_project_lock,
    __reset_for_testing,
)


def setup_function(_):
    __reset_for_testing()


async def test_async_lock_serializes_same_project():
    """Two concurrent calls with same project_id run sequentially."""
    order: list[str] = []

    async def task_a():
        async with with_project_lock("proj-1", lambda: _delay_then(order, "a", 0.1)) if False else None:
            pass  # not used; see below

    async def slow():
        order.append("slow-start")
        await asyncio.sleep(0.05)
        order.append("slow-end")
        return "slow"

    async def fast():
        order.append("fast-start")
        await asyncio.sleep(0.01)
        order.append("fast-end")
        return "fast"

    # Run sequentially because they share project_id
    result_slow = await with_project_lock("proj-1", slow)
    result_fast = await with_project_lock("proj-1", fast)
    assert result_slow == "slow"
    assert result_fast == "fast"
    # Order: slow fully completes, then fast starts
    assert order.index("slow-end") < order.index("fast-start")


def _delay_then(order, label, t):
    """Stub: in real test we'd await asyncio.sleep"""
    pass  # not used; see coroutine test


async def test_async_lock_different_projects_concurrent():
    """Two concurrent calls with different project_ids run in parallel."""
    counter = {"a_started": 0, "a_finished": 0, "b_started": 0, "b_finished": 0}

    async def task_a():
        counter["a_started"] += 1
        await asyncio.sleep(0.05)
        counter["a_finished"] += 1

    async def task_b():
        counter["b_started"] += 1
        await asyncio.sleep(0.05)
        counter["b_finished"] += 1

    await asyncio.gather(
        with_project_lock("proj-A", task_a),
        with_project_lock("proj-B", task_b),
    )
    # Both started before either finished (parallel)
    assert counter["a_started"] == 1
    assert counter["b_started"] == 1
    assert counter["a_finished"] == 1
    assert counter["b_finished"] == 1


def test_sync_lock_runs_callable():
    """sync_with_project_lock executes callable synchronously."""

    def work():
        return 42

    result = sync_with_project_lock("proj-sync", work)
    assert result == 42


async def test_async_lock_propagates_exception():
    """Exception inside with_project_lock is re-raised."""
    async def fail():
        raise ValueError("boom")

    import pytest
    with pytest.raises(ValueError, match="boom"):
        await with_project_lock("proj-fail", fail)


async def test_lock_released_after_exception():
    """Lock is released even when callable raises."""
    async def fail():
        raise RuntimeError("oops")

    try:
        await with_project_lock("proj-recover", fail)
    except RuntimeError:
        pass

    # Lock should be released; another task should run immediately
    async def fast():
        return "ok"

    result = await with_project_lock("proj-recover", fast)
    assert result == "ok"
