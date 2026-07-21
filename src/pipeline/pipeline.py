# ruflo-kb/src/pipeline/pipeline.py
import asyncio
from ..events.event_bus import event_bus
from ..events.events import EventName
from ..queue.queue import update_task_status
from ..types import TaskStatus
from .collector import collect
from .processor import process
from .librarian import archive

event_bus.on("collector:start", lambda p: _on_collector_start(p))
event_bus.on(EventName.COLLECTOR_DONE, lambda p: _on_collector_done(p))
event_bus.on(EventName.PROCESSOR_DONE, lambda p: _on_processor_done(p))

def _on_collector_start(payload: dict):
    task_id = payload["task_id"]
    update_task_status(task_id, TaskStatus.RUNNING)
    asyncio.create_task(collect(task_id, payload["source"], payload["source_type"]))

async def _on_collector_done(payload):
    task_id = payload.task_id
    await process(task_id, payload.raw_path, payload.content)

async def _on_processor_done(payload):
    task_id = payload.task_id
    await archive(task_id, payload.note_path)
