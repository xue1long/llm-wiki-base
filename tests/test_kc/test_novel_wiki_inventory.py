from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.kc_novel_wiki_inventory import inventory, select_stratified_sources


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "staging"
    (project / "raw" / "sources").mkdir(parents=True)
    (project / "schema.md").write_text("schema", encoding="utf-8")
    (project / "purpose.md").write_text("purpose", encoding="utf-8")
    return project


def test_inventory_covers_each_source_without_provider(tmp_path: Path) -> None:
    project = _project(tmp_path)
    (project / "raw" / "sources" / "a.md").write_text("有效正文内容足够长，可以作为证据。", encoding="utf-8")
    (project / "raw" / "sources" / "b.bin").write_bytes(b"binary")
    output = tmp_path / "inventory.json"

    report = inventory(project, output=output, policy_version="content-policy-v1")

    assert report["selected"] == 2
    assert {item["source_id"] for item in report["records"]} == {
        "raw/sources/a.md", "raw/sources/b.bin"
    }
    assert all("decision" in item for item in report["records"])
    assert json.loads(output.read_text(encoding="utf-8"))["selected"] == 2


def test_inventory_rejects_protected_root_overlap(tmp_path: Path) -> None:
    protected = tmp_path / "knowledge" / "novel-wiki"
    project = _project(protected)

    with pytest.raises(ValueError, match="protected root"):
        inventory(
            project,
            output=tmp_path / "report.json",
            policy_version="content-policy-v1",
            protected_root=protected,
        )


def test_stratified_selection_is_deterministic_and_category_aware() -> None:
    report = {
        "records": [
            {"source_id": "raw/1.md", "stratum": "ready:prose"},
            {"source_id": "raw/2.md", "stratum": "ready:prose"},
            {"source_id": "raw/3.md", "stratum": "skip_no_content:prose"},
            {"source_id": "raw/4.md", "stratum": "unsupported:unknown"},
        ]
    }

    first = select_stratified_sources(report, limit=3, seed=20260830)
    second = select_stratified_sources(report, limit=3, seed=20260830)

    assert first == second
    assert len(first) == 3
    assert {item for item in first} >= {"raw/3.md", "raw/4.md"}
