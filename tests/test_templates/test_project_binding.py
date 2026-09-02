import json
from pathlib import Path

from src.project.identity import ProjectIdentity, resolve_project_template
from src.templates.contract import load_template_snapshot
from src.types import IngestSnapshot, KnowledgeTask, SourceType, TaskStatus


def _project(root: Path) -> None:
    (root / ".wiki-templates").mkdir()
    (root / "schema.md").write_text(
        "| type | directory |\n|------|-----------|\n| concept | wiki/concepts |\n",
        encoding="utf-8",
    )
    (root / "purpose.md").write_text("purpose", encoding="utf-8")
    (root / ".wiki-templates" / "concept.md").write_text(
        "<!-- wiki-template-version: 1.0.0 -->\n"
        "<!-- wiki-template-type: concept -->\n\n## Definition\n<!-- slot:definition -->\n",
        encoding="utf-8",
    )


def test_resolve_project_template_persists_binding_and_snapshot(tmp_path: Path):
    _project(tmp_path)

    snapshot, _ = resolve_project_template(tmp_path)
    identity = ProjectIdentity.from_dict(
        json.loads((tmp_path / ".llm-wiki" / "project.json").read_text(encoding="utf-8"))
    )

    assert snapshot.contract_hash
    assert identity.template_id == "general@compat"
    assert load_template_snapshot(tmp_path, snapshot.contract_hash).template_id == "general@compat"


def test_ingest_snapshot_round_trips():
    snapshot = IngestSnapshot(
        instance_id="p1",
        source_identity="source:a",
        source_version="v1",
        template_snapshot={"contract_hash": "abc"},
        pipeline_contract_version="1",
    )
    assert IngestSnapshot.from_dict(snapshot.to_dict()) == snapshot


def test_knowledge_task_legacy_defaults_remain_loadable():
    task = KnowledgeTask.from_dict({
        "id": "t1", "source": "a.md", "source_type": "file",
        "status": "pending", "task_hash": "h", "created_at": 1, "updated_at": 1,
    })
    assert task.ingest_snapshot is None
