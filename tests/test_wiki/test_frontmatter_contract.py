"""Regression test for the novel-wiki V4/V5 on-disk frontmatter contract."""

from src.wiki.core.types import PageType, WikiPage


V5_KEYS = {
    "id",
    "title",
    "type",
    "relations",
    "tags",
    "sources",
    "created_at",
    "updated_at",
}


def test_to_frontmatter_dict_emits_only_v5_keys():
    page = WikiPage(
        id="contract-page",
        title="Contract page",
        type=PageType.CONCEPT,
        body="正文",
        processing_depth="memory",
        workflow_state="verified",
        category="写作技法",
        taxonomy_sub="人物",
    )

    assert set(page.to_frontmatter_dict()) == V5_KEYS
