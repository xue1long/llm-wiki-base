# tests/test_wiki/test_schema_routing.py
import yaml
from pathlib import Path

from src.wiki.types import PageType, WikiPage
from src.wiki.schema_routing import validate_schema_routing
from src.wiki.ensure import ensure_knowledge_base
from src.wiki.paths import WikiPaths
from src.wiki.page_writer import write_page


def test_validate_clean_wiki(tmp_path):
    """Pages in correct subdirs → empty violation list."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    write_page(p, WikiPage(id="src-1", title="S", type=PageType.SOURCE, body=""))
    write_page(p, WikiPage(id="ent-1", title="E", type=PageType.ENTITY, body=""))
    write_page(p, WikiPage(id="con-1", title="C", type=PageType.CONCEPT, body=""))
    write_page(p, WikiPage(id="syn-1", title="Y", type=PageType.SYNTHESIS, body=""))

    violations = validate_schema_routing(p)
    assert violations == []


def test_validate_detects_misrouted(tmp_path):
    """A page whose frontmatter type doesn't match its subdir → violation."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    # Write a page with type=ENTITY but manually move it to wiki_sources/
    page = WikiPage(id="mis-1", title="Mis", type=PageType.ENTITY, body="x")
    write_page(p, page)
    misrouted_file = p.wiki_sources / "mis-1.md"
    misrouted_file.parent.mkdir(parents=True, exist_ok=True)
    fm = page.to_frontmatter_dict()
    fm_text = yaml.dump(fm, allow_unicode=True, sort_keys=False, default_flow_style=False)
    misrouted_file.write_text(f"---\n{fm_text}---\n\n{page.body}", encoding="utf-8")

    violations = validate_schema_routing(p)
    assert any("mis-1" in v for v in violations)
    assert any("wiki_sources" in v for v in violations)