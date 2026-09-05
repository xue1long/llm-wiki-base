import asyncio
import json
from pathlib import Path

from src.kc.views.book.wiki.model import ContentBlock, PageRecord, WikiSnapshot
from src.kc.views.book.wiki.theme_outline import (
    plan_theme_outline, place_page_summaries, validate_theme_outline,
)
from src.kc.views.book.wiki.compiler import build_from_wiki


class OutlineProvider:
    async def complete(self, messages, **kwargs):
        return type("Response", (), {"content": json.dumps({
            "volumes": [{"title": "写作基础", "description": "基础方法", "chapters": [
                {"title": "选题", "description": "选题方法"},
                {"title": "开篇", "description": "开篇方法"},
            ]}],
        })})()


def test_theme_outline_does_not_need_wiki():
    result = asyncio.run(plan_theme_outline(theme="网文写作", purpose="可执行知识库", provider=OutlineProvider()))
    assert result["source_mode"] == "theme_only"
    assert result["wiki_snapshot"] is None
    assert result["volumes"][0]["volume_id"] == "v001"
    assert result["volumes"][0]["chapters"][0]["chapter_id"] == "v001-c001"
    assert validate_theme_outline(result, theme="网文写作", purpose="可执行知识库") == ()


def test_summary_mapping_preserves_pages_and_adds_fallback():
    pages = tuple(PageRecord(f"p{i}", f"Page {i}", "concept", f"concepts/p{i}.md", None,
                             f"Summary {i}", (ContentBlock(f"p{i}:0", f"p{i}", None, f"Body {i}", 0),), (), f"h{i}", 6, None)
                  for i in range(2))
    snapshot = WikiSnapshot("snap", str(Path("/tmp/wiki")), "v2", pages, ())

    class Mapper:
        async def complete(self, messages, **kwargs):
            payload = json.loads(messages[0]["content"])
            return type("Response", (), {"content": json.dumps({
                "assignments": [{"page_id": payload["pages"][0]["page_id"], "chapter_id": "v001-c001"}],
            })})()

    outline = asyncio.run(plan_theme_outline(theme="网文写作", purpose="可执行知识库", provider=OutlineProvider()))
    runtime = asyncio.run(place_page_summaries(outline, snapshot, Mapper(), batch_size=2))
    assigned = [pid for v in runtime["volumes"] for c in v["chapters"] for pid in c["page_ids"]]
    assert sorted(assigned) == ["p0", "p1"]
    assert any(v["volume_id"] == "v999" for v in runtime["volumes"])


def test_build_from_wiki_can_consume_theme_outline(tmp_path):
    project = tmp_path / "project"
    (project / ".llm-wiki").mkdir(parents=True)
    (project / ".llm-wiki" / "project.json").write_text('{"schema_version":"v2.0"}', encoding="utf-8")
    for name in ("concepts", "entities", "synthesis"):
        (project / "wiki" / name).mkdir(parents=True)
    (project / "wiki" / "concepts" / "p0.md").write_text(
        "---\nid: p0\ntitle: Page 0\ntype: concept\n---\nBody 0\n", encoding="utf-8")
    outline = asyncio.run(plan_theme_outline(theme="网文写作", purpose="", provider=OutlineProvider()))
    outline_path = project / ".llm-wiki" / "book" / "theme-outline.json"
    outline_path.parent.mkdir(parents=True)
    outline_path.write_text(json.dumps(outline, ensure_ascii=False), encoding="utf-8")

    class Mapper:
        async def complete(self, messages, **kwargs):
            payload = json.loads(messages[0]["content"])
            return type("Response", (), {"content": json.dumps({
                "assignments": [{"page_id": payload["pages"][0]["page_id"], "chapter_id": "v001-c001"}],
            })})()

    result = build_from_wiki(project, output_dir=project / "book-wiki", use_llm=True,
                             theme_outline=outline_path, provider=Mapper())
    assert result["status"] == "planned"
    manifest = json.loads((Path(result["version_dir"]) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["outline_generation_mode"] == "theme_mapped"
