from src.types import IngestSnapshot, SourceType
from src.utils.idempotency import generate_task_hash


def test_contract_hash_changes_task_identity_but_legacy_hash_stays_stable():
    base = generate_task_hash(SourceType.FILE, "raw/a.md", project_id="p1")
    legacy = generate_task_hash(SourceType.FILE, "raw/a.md", project_id="p1", contract_hash="")
    changed = generate_task_hash(SourceType.FILE, "raw/a.md", project_id="p1", contract_hash="contract-2")

    assert legacy == base
    assert changed != base


def test_ingest_snapshot_round_trips_as_task_data():
    snapshot = IngestSnapshot(
        instance_id="p1", source_identity="raw/a.md", source_version="v1",
        template_snapshot={"contract_hash": "c1"}, pipeline_contract_version="1",
    )
    assert IngestSnapshot.from_dict(snapshot.to_dict()) == snapshot
