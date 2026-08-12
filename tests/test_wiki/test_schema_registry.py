"""Tests for SchemaRegistry — custom page type parser."""
from src.wiki.schema_registry import SchemaRegistry, _parse_schema_text


def test_parse_schema_with_custom_types():
    schema = """| type     | directory      |
|----------|----------------|
| source   | wiki/sources   |
| entity   | wiki/entities  |
| thesis   | wiki/thesis    |
| finding  | wiki/findings  |
"""
    reg = SchemaRegistry.from_schema_text(schema)
    assert reg.all_custom_type_names() == ["finding", "thesis"]

    thesis = reg.get_def("thesis")
    assert thesis is not None
    assert thesis.name == "thesis"
    assert thesis.directory == "thesis"
    assert thesis.extends.value == "concept"

    finding = reg.get_def("finding")
    assert finding is not None
    assert finding.directory == "findings"


def test_parse_schema_only_builtin():
    schema = """| type   | directory    |
|--------|--------------|
| source | wiki/sources |
| entity | wiki/entities |
"""
    reg = SchemaRegistry.from_schema_text(schema)
    assert reg.all_custom_type_names() == []


def test_parse_schema_missing_file(tmp_path):
    reg = SchemaRegistry.from_project(tmp_path)
    assert reg.all_custom_type_names() == []


def test_empty_registry():
    reg = SchemaRegistry.empty()
    assert reg.all_custom_type_names() == []
    assert reg.get_def("thesis") is None
    assert reg.get_directory("thesis") is None
    assert reg.get_base_type("thesis") == reg.get_base_type("concept")
    assert not reg.is_custom("anything")


def test_is_custom_and_get_base_type():
    schema = "| type | directory |\n|------|-----------|\n| thesis | wiki/thesis |\n"
    reg = SchemaRegistry.from_schema_text(schema)
    assert reg.is_custom("thesis")
    assert not reg.is_custom("source")
    assert reg.get_base_type("thesis").value == "concept"
    assert reg.get_base_type("unknown").value == "concept"


def test_all_type_names_union():
    schema = "| type | directory |\n|------|-----------|\n| thesis | wiki/thesis |\n"
    reg = SchemaRegistry.from_schema_text(schema)
    names = reg.all_type_names()
    assert "thesis" in names
    assert "source" in names
    assert "entity" in names
    assert "concept" in names


def test_extends_column():
    schema = "| type | directory | extends |\n|------|-----------|---------|\n| character | wiki/characters | entity |\n"
    reg = SchemaRegistry.from_schema_text(schema)
    assert reg.get_def("character").extends.value == "entity"
    assert reg.get_base_type("character").value == "entity"


def test_parse_handles_separator_rows():
    """Pipes with dashes/colons like |------|-----------| should be ignored."""
    schema = "| type | directory |\n|------|-----------|\n| thesis | wiki/thesis |\n"
    reg = SchemaRegistry.from_schema_text(schema)
    assert reg.all_custom_type_names() == ["thesis"]


def test_parse_handles_extra_whitespace():
    schema = "  |  type  |  directory  |  \n  | thesis | wiki/thesis |  "
    reg = SchemaRegistry.from_schema_text(schema)
    assert reg.all_custom_type_names() == ["thesis"]


def test_parse_preserves_safe_nested_directory_and_rejects_traversal():
    schema = """| type | directory |
|------|-----------|
| thesis | wiki/research/thesis |
| escape | wiki/../outside |
| absolute | C:/outside |
"""
    reg = SchemaRegistry.from_schema_text(schema)
    assert reg.get_directory("thesis") == "research/thesis"
    assert not reg.is_custom("escape")
    assert not reg.is_custom("absolute")


def test_custom_page_round_trips_and_writes_to_schema_directory(tmp_path):
    from src.wiki.core.paths import WikiPaths
    from src.wiki.core.types import PageType, WikiPage
    from src.wiki.storage.page_writer import read_page, write_page

    (tmp_path / "schema.md").write_text(
        "| type | directory |\n|------|-----------|\n| thesis | wiki/thesis |\n",
        encoding="utf-8",
    )
    page = WikiPage(
        id="argument", title="Argument", type=PageType.CONCEPT,
        custom_type="thesis", body="Body",
    )
    write_page(WikiPaths(tmp_path), page)

    path = tmp_path / "wiki" / "thesis" / "argument.md"
    assert path.exists()
    loaded = read_page(path)
    assert loaded.type == PageType.CONCEPT
    assert loaded.custom_type == "thesis"


def test_ensure_creates_declared_custom_directories(tmp_path):
    from src.wiki.storage.ensure import ensure_knowledge_base

    registry = SchemaRegistry.from_schema_text(
        "| type | directory |\n| thesis | wiki/research/thesis |"
    )
    ensure_knowledge_base(tmp_path, registry)
    assert (tmp_path / "wiki" / "research" / "thesis").is_dir()
