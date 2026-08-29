import yaml

from src.wiki.core.paths import WikiPaths
from src.wiki.core.types import PageType, WikiPage
from src.wiki.features.gbrain_compat import (
    build_target_slugs,
    gbrain_slug_for_path,
    rewrite_wikilinks,
    materialize_relations,
)
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.storage.page_writer import page_path_for, write_page
from src.wiki.features.relations import Relation


def test_write_page_persists_path_qualified_gbrain_slug(tmp_path):
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    write_page(paths, WikiPage(id="暗器", title="暗器", type=PageType.CONCEPT, body="body"))

    page_path = page_path_for(paths, PageType.CONCEPT, "暗器")
    frontmatter = yaml.safe_load(page_path.read_text(encoding="utf-8").split("---", 2)[1])
    assert frontmatter["slug"] == "concepts/暗器"
    assert gbrain_slug_for_path(paths, page_path) == "concepts/暗器"


def test_rewrite_wikilinks_uses_qualified_targets_and_preserves_aliases():
    mapping = {"暗器": "concepts/暗器", "来源": "sources/来源"}
    assert rewrite_wikilinks("见 [[暗器]] 与 [[来源|原文]]", mapping) == (
        "见 [[concepts/暗器]] 与 [[sources/来源|原文]]"
    )


def test_materialize_relations_adds_idempotent_gbrain_links():
    page = WikiPage(
        id="暗器",
        title="暗器",
        type=PageType.CONCEPT,
        body="## 定义\n\n一种兵器。",
        relations=[Relation(target_id="标枪", type="related", weight=1.0)],
    )
    body = materialize_relations(page.body, page.relations, {"标枪": "concepts/标枪"})
    assert "related: [[concepts/标枪]]" in body
    assert materialize_relations(body, page.relations, {"标枪": "concepts/标枪"}) == body


def test_ruflo_read_side_resolves_gbrain_qualified_link(tmp_path):
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    write_page(paths, WikiPage(id="暗器", title="暗器", type=PageType.CONCEPT, body="body"))
    from src.wiki.features.wikilink import resolve_wikilink

    assert resolve_wikilink(tmp_path, "concepts/暗器") is True


def test_target_map_drops_ambiguous_ids(tmp_path):
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    (paths.wiki_entities / "same.md").write_text("x", encoding="utf-8")
    (paths.wiki_concepts / "same.md").write_text("x", encoding="utf-8")
    assert "same" not in build_target_slugs(paths)
