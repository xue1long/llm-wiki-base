import json

import pytest

from src.templates import apply_template, create, list_templates, load, update_content, update_metadata
from src.templates import loader


def test_bundled_scenarios_and_general_page_templates():
    names = {t.name for t in list_templates()}
    assert {"general", "research", "reading", "personal", "business"} <= names
    general = load("general")
    assert ".wiki-templates/source.md" in general.files
    assert ".wiki-templates/entity.md" in general.files
    assert ".wiki-templates/concept.md" in general.files
    assert ".wiki-templates/synthesis.md" in general.files
    assert "taxonomy.md" in load("personal").files


def test_apply_template_creates_extra_dirs_and_preserves_existing(tmp_path):
    (tmp_path / "purpose.md").write_text("keep", encoding="utf-8")
    written = apply_template("research", tmp_path)
    assert (tmp_path / "schema.md").exists()
    assert (tmp_path / "wiki" / "thesis").is_dir()
    assert (tmp_path / "purpose.md").read_text(encoding="utf-8") == "keep"
    assert len(written) >= 2


def test_custom_template_can_be_created_and_updated(tmp_path, monkeypatch):
    monkeypatch.setattr(loader, "USER_DIR", tmp_path / "templates")
    created = create("my-template", source="general")
    assert created.builtin is False
    update_metadata("my-template", description="Changed")
    assert load("my-template").description == "Changed"
    assert json.loads((tmp_path / "templates" / "my-template" / "template.json").read_text(encoding="utf-8"))["description"] == "Changed"


def test_custom_template_can_add_taxonomy_content(tmp_path, monkeypatch):
    monkeypatch.setattr(loader, "USER_DIR", tmp_path / "templates")
    create("my-template", source="general")

    update_content(
        "my-template",
        {"taxonomy.md": "# Taxonomy\n\n## Engineering\n- Python"},
    )

    assert "## Engineering" in load("my-template").files["taxonomy.md"]


def test_bundled_template_cannot_be_updated_or_deleted():
    with pytest.raises(PermissionError):
        update_metadata("general", description="no")


def test_novel_bundled_template_registered():
    ids = {t.name for t in list_templates()}
    assert "novel" in ids
    t = load("novel")
    assert t.builtin is True
    # 必需根级文件齐备
    for must in ("purpose.md", "schema.md", "taxonomy.md", "taxonomy_tags.md"):
        assert must in t.files, f"missing {must}"
    # 四个页面模板齐备
    wt = {f for f in t.files if f.startswith(".wiki-templates/")}
    assert wt == {
        ".wiki-templates/source.md",
        ".wiki-templates/entity.md",
        ".wiki-templates/concept.md",
        ".wiki-templates/synthesis.md",
    }
    # C 决策：页面模板版本头为 2.0.0（非源 3.0.0），规避版本门炸弹且符合 H3
    assert "wiki-template-version: 2.0.0" in t.files[".wiki-templates/concept.md"]


def test_novel_apply_template_scaffold(tmp_path):
    written = apply_template("novel", tmp_path)
    names = {p.name for p in written}
    assert {"purpose.md", "schema.md", "taxonomy.md", "taxonomy_tags.md"} <= names
    # 页面模板落到 .wiki-templates/
    assert (tmp_path / ".wiki-templates" / "concept.md").exists()
    # 应用副本版本头仍为 2.0.0
    head = (tmp_path / ".wiki-templates" / "concept.md").read_text(encoding="utf-8").splitlines()[0]
    assert "wiki-template-version: 2.0.0" in head
