"""TDD contract tests for the unified ingest triage boundary."""

import json

from src.pipeline.triage import TriageResult, triage, write_triage_result
from src.wiki.core.paths import WikiPaths


def test_triage_maps_prefilter_action_to_source_grade():
    result = triage("notes.md", "短", file_size=20)

    assert result == TriageResult(
        source_id="notes.md",
        grade="C",
        action="skip",
        reason="File too small (20 bytes < 100 minimum)",
        rule_version="triage-v1",
        metadata={},
    )


def test_triage_defaults_to_process_b_for_normal_source():
    result = triage("notes.md", "这是一段足够长的中文知识内容。" * 20, file_size=500)

    assert result.action == "process"
    assert result.grade == "B"
    assert result.rule_version == "triage-v1"


def test_write_triage_result_is_jsonl_and_idempotent_for_same_event(tmp_path):
    paths = WikiPaths(tmp_path)
    result = triage("notes.md", "短", file_size=20)

    write_triage_result(paths, result)
    write_triage_result(paths, result)

    records = [json.loads(line) for line in (paths.index / "triage.log").read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1
    assert records[0]["source_id"] == "notes.md"
    assert records[0]["action"] == "skip"
