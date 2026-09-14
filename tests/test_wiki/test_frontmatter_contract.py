"""Regression checks for the novel-wiki V4/V5 to V6 frontmatter contract."""

import importlib.util
import sys
from pathlib import Path

from src.wiki.core.types import PageType, WikiPage


V4_KEYS = {
    "id", "title", "type", "relations", "tags", "sources",
    "created_at", "updated_at",
}
V6_KEYS = V4_KEYS | {
    "processing_depth", "source_grade", "platform", "category",
    "taxonomy_sub", "use_context", "workflow_state", "capture_type",
    "v2_origin", "_ko_extra",
}
# V7.1.1 (RFC v6): the V7 whitelist extends V6 with 4 fields.
V7_KEYS = V6_KEYS | {
    "template_version", "entity_subtype", "policy_kind", "stage",
}


def _validator_module():
    path = Path(__file__).parents[2] / "scripts" / "validate_novel_wiki_frontmatter.py"
    spec = importlib.util.spec_from_file_location("novel_wiki_validator", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _page_text(page_id: str, extra: str = "") -> str:
    return (
        "---\n"
        f"id: {page_id}\n"
        "title: page\n"
        "type: concept\n"
        "relations: []\n"
        "tags: []\n"
        "sources: []\n"
        "created_at: 2026-09-11T00:00:00\n"
        "updated_at: 2026-09-11T00:00:00\n"
        f"{extra}"
        "---\n\nbody\n"
    )


def test_current_writer_emits_v7_and_validator_reads_both_generations(tmp_path):
    page = WikiPage(
        id="contract-page",
        title="Contract page",
        type=PageType.CONCEPT,
        processing_depth="memory",
        workflow_state="verified",
        category="写作技法",
        taxonomy_sub="人物",
    )
    # V7.1.1: writer emits the V7 whitelist (V6's 18 + V7's 4).
    assert set(page.to_frontmatter_dict()) == V7_KEYS

    concepts = tmp_path / "concepts"
    concepts.mkdir()
    legacy = concepts / "legacy-page.md"
    current = concepts / "current-page.md"
    legacy.write_text(_page_text("legacy-page"), encoding="utf-8")
    current.write_text(
        _page_text(
            "current-page",
            "processing_depth: memory\n"
            "source_grade: A\n"
            "platform: test\n"
            "category: writing\n"
            "taxonomy_sub: character\n"
            "use_context: scene\n"
            "workflow_state: verified\n"
            "capture_type: article\n"
            "v2_origin: false\n"
            "_ko_extra: {}\n",
        ),
        encoding="utf-8",
    )

    validator = _validator_module()
    assert not validator.validate_page(legacy, tmp_path).findings
    assert not validator.validate_page(current, tmp_path).findings
