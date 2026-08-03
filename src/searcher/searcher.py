# ruflo-kb/src/searcher/searcher.py
import logging
from ..events.event_bus import event_bus
from ..events.events import EventName
from .hybrid_search import hybrid_search

logger = logging.getLogger(__name__)

event_bus.on(EventName.SEARCHER_QUERY, lambda p: _on_search_query(p))

async def _on_search_query(payload: dict):
    query = payload["query"]

    try:
        results = await hybrid_search(query, top_k=10)
        event_bus.emit(EventName.SEARCHER_RESULT, {"query": query, "results": results})
    except Exception as e:
        logger.error(f"[Searcher] Search failed: {e}")
        event_bus.emit(EventName.SEARCHER_RESULT, {"query": query, "results": []})
