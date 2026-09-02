import json
from pathlib import Path

import pytest

from src.templates.compiler import compile_project_template
from src.templates.contract import load_template_snapshot, persist_template_snapshot


def _project(root: Path) -> None:
    (root / ".wiki-templates").mkdir()
    (root / "schema.md").write_text(
        "| type | directory |\n|------|-----------|\n"
        "| source | wiki/sources |\n| concept | wiki/concepts |\n",
        encoding="utf-8",
    )
    (root / "purpose.md").write_text("A test knowledge base.", encoding="utf-8")
    (root / ".wiki-templates" / "source.md").write_text(
        "<!-- wiki-template-version: 1.0.0 -->\n"
        "<!-- wiki-template-type: source -->\n\n## Summary\n<!-- slot:summary -->\n",
        encoding="utf-8",
    )
    (root / ".wiki-templates" / "concept.md").write_text(
        "<!-- wiki-template-version: 1.0.0 -->\n"
        "<!-- wiki-template-type: concept -->\n\n## Definition\n<!-- slot:definition -->\n",
        encoding="utf-8",
    )


def test_compile_persists_deterministic_complete_snapshot(tmp_path: Path):
    _project(tmp_path)

    snapshot, contract = compile_project_template(
        tmp_path, template_id="test", template_version="1"
    )
    persisted = persist_template_snapshot(tmp_path, contract)

    assert snapshot.contract_hash == persisted.contract_hash
    assert snapshot.template_hash
    assert json.loads(Path(snapshot.snapshot_path).read_text(encoding="utf-8"))["purpose"] == contract.purpose
    assert load_template_snapshot(tmp_path, snapshot.contract_hash) == contract


def test_compile_missing_optional_prompts_uses_empty_instructions(tmp_path: Path):
    _project(tmp_path)

    _, contract = compile_project_template(
        tmp_path, template_id="test", template_version="1"
    )

    assert contract.analyzer_instructions == ""
    assert contract.generator_instructions == ""


def test_load_snapshot_rejects_tampering(tmp_path: Path):
    _project(tmp_path)
    _, contract = compile_project_template(tmp_path, template_id="test", template_version="1")
    snapshot = persist_template_snapshot(tmp_path, contract)
    path = Path(snapshot.snapshot_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["purpose"] = "tampered"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="hash mismatch"):
        load_template_snapshot(tmp_path, snapshot.contract_hash)


def test_template_hash_ignores_unrelated_project_data(tmp_path: Path):
    _project(tmp_path)
    first, _ = compile_project_template(tmp_path, template_id="test", template_version="1")
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "page.md").write_text("data", encoding="utf-8")
    second, _ = compile_project_template(tmp_path, template_id="test", template_version="1")

    assert second.template_hash == first.template_hash
