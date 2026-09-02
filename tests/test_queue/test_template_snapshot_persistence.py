from pathlib import Path

from src.queue.persistence import JsonFileBackend
from src.types import IngestSnapshot, KnowledgeTask, SourceType, TaskStatus


def test_queue_persists_and_restores_ingest_snapshot(tmp_path: Path):
    backend = JsonFileBackend(tmp_path / "queue.json")
    task = KnowledgeTask(
        id="t1", source="raw/a.md", source_type=SourceType.FILE,
        status=TaskStatus.PENDING, task_hash="h", created_at=1, updated_at=1,
        ingest_snapshot=IngestSnapshot(
            instance_id="p1", source_identity="raw/a.md", source_version="v1",
            template_snapshot={"contract_hash": "c1"}, pipeline_contract_version="1",
        ),
    )
    backend.enqueue(task)

    restored = JsonFileBackend(tmp_path / "queue.json").find("t1")

    assert restored is not None
    assert restored.ingest_snapshot == task.ingest_snapshot
