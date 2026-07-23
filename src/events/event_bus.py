# ruflo-kb/src/events/event_bus.py
from typing import Callable, Any
import logging

logger = logging.getLogger(__name__)

EventHandler = Callable[[Any], None]

class EventBus:
    def __init__(self, fail_fast: bool = False):
        # fail_fast: when True, the first handler exception aborts emit and
        # re-raises. Default False (backwards compatible) — exceptions are
        # logged and remaining handlers continue to run.
        self.fail_fast: bool = fail_fast
        self._handlers: dict[str, set[EventHandler]] = {}

    def on(self, event: str, handler: EventHandler) -> Callable[[], None]:
        if event not in self._handlers:
            self._handlers[event] = set()
        self._handlers[event].add(handler)

        def unsubscribe():
            self._handlers[event].discard(handler)

        return unsubscribe

    def emit(self, event: str, payload: Any) -> None:
        # Snapshot iteration: list() copies the handler set so handlers that
        # subscribe or unsubscribe during emit don't trigger
        # "RuntimeError: Set changed size during iteration".
        # Handlers added during this emit are NOT called for the current emit
        # (they become visible on the next emit) — matching the natural
        # "freeze the handler list at emit-start" semantics.
        handlers = list(self._handlers.get(event, ()))
        for handler in handlers:
            try:
                handler(payload)
            except Exception as e:
                logger.error(
                    f"[EventBus] Handler error for {event}: {e}",
                    extra={"event": event, "handler": handler.__qualname__},
                )
                if self.fail_fast:
                    raise

    def off(self, event: str, handler: EventHandler) -> None:
        self._handlers.get(event, set()).discard(handler)

event_bus = EventBus()
