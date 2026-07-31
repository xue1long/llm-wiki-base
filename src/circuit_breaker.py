# ruflo-kb/src/circuit_breaker.py
"""
超时/熔断机制

- 任务超时控制
- 失败次数达到阈值后熔断
- 死信目录处理
"""

import asyncio
import inspect
import logging
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Optional
from functools import wraps

logger = logging.getLogger(__name__)

class CircuitState(str, Enum):
    CLOSED = "closed"      # 正常状态
    OPEN = "open"          # 熔断状态
    HALF_OPEN = "half_open"  # 半开状态（尝试恢复）

@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 10     # 失败次数达到此值则熔断（3太敏感，LLM 偶尔超时/解析失败不应全队列阻塞）
    recovery_timeout: int = 60     # 60秒后尝试恢复
    success_threshold: int = 2      # 半开状态下成功次数达到此值则恢复

@dataclass
class CircuitBreaker:
    """
    熔断器

    状态转换:
    CLOSED -> OPEN: 连续失败达到阈值
    OPEN -> HALF_OPEN: 超时后
    HALF_OPEN -> CLOSED: 连续成功达到阈值
    HALF_OPEN -> OPEN: 任何失败
    """
    name: str
    config: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: Optional[datetime] = None
    opened_at: Optional[datetime] = None
    on_state_change: Optional[Callable[[CircuitState, CircuitState], None]] = None

    def record_success(self) -> None:
        """记录成功"""
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.config.success_threshold:
                self._transition_to(CircuitState.CLOSED)
        else:
            self.failure_count = 0
            self.success_count = 0

    def record_failure(self) -> None:
        """记录失败"""
        self.failure_count += 1
        self.last_failure_time = datetime.now()

        if self.state == CircuitState.HALF_OPEN:
            self._transition_to(CircuitState.OPEN)
        elif self.state != CircuitState.OPEN and self.failure_count >= self.config.failure_threshold:
            self._transition_to(CircuitState.OPEN)

    def can_execute(self) -> bool:
        """检查是否可以执行"""
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            if self._should_attempt_recovery():
                self._transition_to(CircuitState.HALF_OPEN)
                return True
            return False

        # HALF_OPEN 状态可以执行
        return True

    def _should_attempt_recovery(self) -> bool:
        """检查是否应该尝试恢复"""
        if not self.opened_at:
            return True
        elapsed = datetime.now() - self.opened_at
        return elapsed.total_seconds() >= self.config.recovery_timeout

    def _transition_to(self, new_state: CircuitState) -> None:
        """状态转换"""
        previous_state = self.state
        logger.info(f"[CircuitBreaker:{self.name}] {previous_state.value} -> {new_state.value}")
        self.state = new_state

        if new_state == CircuitState.OPEN:
            self.opened_at = datetime.now()
            self.failure_count = 0
        elif new_state == CircuitState.HALF_OPEN:
            self.success_count = 0
        elif new_state == CircuitState.CLOSED:
            self.failure_count = 0
            self.success_count = 0
            self.opened_at = None

        if self.on_state_change is not None:
            self.on_state_change(previous_state, new_state)


# 全局熔断器实例
_circuit_breakers: dict[str, CircuitBreaker] = {}


def circuit_breaker(
    name: str = "default",
    config: Optional[CircuitBreakerConfig] = None,
    *,
    on_state_change: Optional[Callable[[CircuitState, CircuitState], None]] = None,
):
    """Decorate a sync or async callable with a named shared breaker."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        breaker = _circuit_breakers.setdefault(
            name,
            CircuitBreaker(
                name=name,
                config=config or CircuitBreakerConfig(),
                on_state_change=on_state_change,
            ),
        )

        if inspect.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                if not breaker.can_execute():
                    raise CircuitOpenError(f"Circuit {name} is OPEN")

                try:
                    result = await func(*args, **kwargs)
                except Exception:
                    breaker.record_failure()
                    raise
                breaker.record_success()
                return result

            async_wrapper.circuit_breaker = breaker
            return async_wrapper

        @wraps(func)
        def wrapper(*args, **kwargs):
            if not breaker.can_execute():
                raise CircuitOpenError(f"Circuit {name} is OPEN")

            try:
                result = func(*args, **kwargs)
            except Exception:
                breaker.record_failure()
                raise
            breaker.record_success()
            return result

        wrapper.circuit_breaker = breaker
        return wrapper

    return decorator


class CircuitOpenError(Exception):
    """熔断器开启异常"""
    pass


def get_circuit_breaker(name: str) -> CircuitBreaker:
    """获取或创建熔断器"""
    if name not in _circuit_breakers:
        _circuit_breakers[name] = CircuitBreaker(name=name)
    return _circuit_breakers[name]

def circuit_state(name: str) -> CircuitState:
    """获取熔断器状态"""
    return get_circuit_breaker(name).state
