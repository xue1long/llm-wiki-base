from pathlib import Path

import pytest

from src.templates.compiler import compile_project_template


def test_compile_rejects_declared_type_without_page_template(tmp_path: Path):
    (tmp_path / ".wiki-templates").mkdir()
    (tmp_path / "schema.md").write_text(
        "| type | directory |\n|------|-----------|\n| source | wiki/sources |\n",
        encoding="utf-8",
    )
    (tmp_path / "purpose.md").write_text("purpose", encoding="utf-8")

    with pytest.raises(ValueError, match="missing page template"):
        compile_project_template(tmp_path, template_id="bad", template_version="1")


def test_compile_rejects_template_type_not_declared_by_schema(tmp_path: Path):
    (tmp_path / ".wiki-templates").mkdir()
    (tmp_path / "schema.md").write_text(
        "| type | directory |\n|------|-----------|\n| source | wiki/sources |\n",
        encoding="utf-8",
    )
    (tmp_path / "purpose.md").write_text("purpose", encoding="utf-8")
    (tmp_path / ".wiki-templates" / "source.md").write_text(
        "<!-- wiki-template-version: 1.0.0 -->\n"
        "<!-- wiki-template-type: source -->\n\n## Summary\n<!-- slot:summary -->\n",
        encoding="utf-8",
    )
    (tmp_path / ".wiki-templates" / "concept.md").write_text(
        "<!-- wiki-template-version: 1.0.0 -->\n"
        "<!-- wiki-template-type: concept -->\n\n## Definition\n<!-- slot:definition -->\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="not declared"):
        compile_project_template(tmp_path, template_id="bad", template_version="1")
