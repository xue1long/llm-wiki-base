from types import SimpleNamespace

from src.pipeline.shadow import compare_contracts, rollback_task
from src.pipeline.task_contract import TaskContext


class Registry:
    def visible_block_ids(self):
        return ["b1"]

    def get(self, block_id):
        return SimpleNamespace(visible=block_id == "b1", canonical_content="evidence")


def test_compare_contracts_is_local_and_reports_v2():
    candidate = {"source_id": "source", "claims": [{"statement": "claim", "evidence_block_ids": ["b1"]}]}
    context = TaskContext.create("task", "source.md", "text", template_version="tpl", contract_version="v2")
    report = compare_contracts(candidate, "text", Registry(), context)
    assert report.contract_version == "v2"
    assert report.llm_calls == 0
    assert report.writer_calls == 0
    assert report.blocked is False


def test_rollback_quarantines_unpublished_bundle(tmp_path):
    staging = tmp_path / ".index" / "staging" / "task-v2"
    staging.mkdir(parents=True)
    (staging / "manifest.json").write_text('{"contract_version":"v2"}', encoding="utf-8")
    result = rollback_task("task-v2", tmp_path)
    assert result.status == "quarantined"
    assert not (tmp_path / "wiki").exists()
