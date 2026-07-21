# ruflo-kb/src/events/event_bus.py
from typing import Callable, Any
import logging

logger = logging.getLogger(__name__)

EventHandler = Callable[[Any], None]

class EventBus:
    def __init__(self):
        self._handlers: dict[str, set[EventHandler]] = {}

    def on(self, event: str, handler: EventHandler) -> Callable[[], None]:
        if event not in self._handlers:
            self._handlers[event] = set()
        self._handlers[event].add(handler)

        def unsubscribe():
            self._handlers[event].discard(handler)

        return unsubscribe

    def emit(self, event: str, payload: Any) -> None:
        handlers = self._handlers.get(event, set())
        for handler in handlers:
            try:
                handler(payload)
            except Exception as e:
                logger.error(f"[EventBus] Handler error for {event}: {e}")

    def off(self, event: str, handler: EventHandler) -> None:
        self._handlers.get(event, set()).discard(handler)

event_bus = EventBus()
