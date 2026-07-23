import asyncio

import pytest

from src.circuit_breaker import (
    CircuitBreakerConfig,
    CircuitState,
    _circuit_breakers,
    circuit_breaker,
    get_circuit_breaker,
)


def setup_function(_):
    _circuit_breakers.clear()


def test_decorator_shares_state_with_get_for_sync_function():
    @circuit_breaker(name="x")
    def operation():
        return 1

    assert operation() == 1
    assert get_circuit_breaker("x") is operation.circuit_breaker


def test_decorator_shares_state_with_get_for_async_function():
    @circuit_breaker(name="async-x")
    async def operation():
        return 1

    assert asyncio.run(operation()) == 1
    assert get_circuit_breaker("async-x") is operation.circuit_breaker


def test_decorator_reuses_existing_registered_breaker():
    registered = get_circuit_breaker("existing")

    @circuit_breaker(
        name="existing",
        config=CircuitBreakerConfig(failure_threshold=99),
    )
    async def operation():
        return 1

    assert operation.circuit_breaker is registered


def test_decorator_registers_config_and_state_change_callback():
    transitions = []
    config = CircuitBreakerConfig(failure_threshold=1)

    @circuit_breaker(
        name="configured",
        config=config,
        on_state_change=lambda old, new: transitions.append((old, new)),
    )
    async def operation():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(operation())

    breaker = get_circuit_breaker("configured")
    assert breaker.config is config
    assert transitions == [(CircuitState.CLOSED, CircuitState.OPEN)]
