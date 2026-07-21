# ruflo-kb/src/orchestrator/orchestrator.py
import logging
from pathlib import Path

from ..events.event_bus import event_bus
from ..events.events import EventName, ProcessorDonePayload, LibrarianDonePayload
from ..queue.queue import enqueue_task, update_task_status
from .router import route_task, parse_source, TaskIntent
from .audit_hard import run_hard_audit
from .state_machine import can_transition, get_next_status

logger = logging.getLogger(__name__)

class Orchestrator:
    def process(self, input_text: str) -> dict:
        intent = route_task(input_text)

        if intent == TaskIntent.SEARCH:
            return self._handle_search(input_text)
        return self._handle_ingest(input_text)

    def _handle_ingest(self, input_text: str) -> dict:
        source, source_type = parse_source(input_text)
        from ..types import SourceType
        from ..utils.idempotency import generate_task_hash

        task_hash = generate_task_hash(
            SourceType(source_type),
            source,
            ""
        )
        task_id = enqueue_task(source, SourceType(source_type), task_hash)

        if not task_id:
            return {"status": "ignored", "reason": "重复提交"}

        return {"status": "queued", "task_id": task_id}

    def _handle_search(self, query: str) -> dict:
        clean_query = query.lstrip("? ").replace("search:", "").replace("find:", "").strip()
        event_bus.emit(EventName.SEARCHER_QUERY, {"query": clean_query, "mode": "hybrid"})
        return {"status": "searching", "query": clean_query}

def get_orchestrator() -> Orchestrator:
    return _orchestrator_instance

_orchestrator_instance = Orchestrator()

# 注册事件监听
event_bus.on(EventName.PROCESSOR_DONE, lambda payload: _on_processor_done(payload))
event_bus.on(EventName.LIBRARIAN_DONE, lambda payload: _on_librarian_done(payload))

def _on_processor_done(payload: ProcessorDonePayload):
    """Processor 完成后触发硬规则审核"""
    task_id = payload.task_id
    result = run_hard_audit(payload.note_path)

    if result.passed:
        update_task_status(task_id, "approved")
    else:
        update_task_status(task_id, "rejected", "; ".join(result.reasons))

def _on_librarian_done(payload: LibrarianDonePayload):
    """归档完成后标记为完成"""
    update_task_status(payload.task_id, "archived")
