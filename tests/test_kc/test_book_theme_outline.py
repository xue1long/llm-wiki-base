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


class FencedOutlineProvider(OutlineProvider):
    async def complete(self, messages, **kwargs):
        response = await super().complete(messages, **kwargs)
        return type("Response", (), {"content": f"```json\n{response.content}\n```"})()


class WrappedOutlineProvider(OutlineProvider):
    async def complete(self, messages, **kwargs):
        response = await super().complete(messages, **kwargs)
        return type("Response", (), {"content": json.dumps({"book": json.loads(response.content)})})()


class TrailingTextOutlineProvider(OutlineProvider):
    async def complete(self, messages, **kwargs):
        response = await super().complete(messages, **kwargs)
        return type("Response", (), {"content": response.content + "\\nExtra note"})()


def test_theme_outline_does_not_need_wiki():
    result = asyncio.run(plan_theme_outline(theme="网文写作", purpose="可执行知识库", provider=OutlineProvider()))
    assert result["source_mode"] == "theme_only"
    assert result["wiki_snapshot"] is None
    assert result["volumes"][0]["volume_id"] == "v001"
    assert result["volumes"][0]["chapters"][0]["chapter_id"] == "v001-c001"
    assert validate_theme_outline(result, theme="网文写作", purpose="可执行知识库") == ()


def test_theme_outline_accepts_json_code_fence():
    result = asyncio.run(plan_theme_outline(theme="网文写作", purpose="", provider=FencedOutlineProvider()))
    assert len(result["volumes"][0]["chapters"]) == 2


def test_theme_outline_accepts_book_wrapper():
    result = asyncio.run(plan_theme_outline(theme="网文写作", purpose="", provider=WrappedOutlineProvider()))
    assert len(result["volumes"][0]["chapters"]) == 2


def test_theme_outline_ignores_trailing_text():
    result = asyncio.run(plan_theme_outline(theme="网文写作", purpose="", provider=TrailingTextOutlineProvider()))
    assert len(result["volumes"][0]["chapters"]) == 2


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


def test_summary_mapping_accepts_chapter_to_page_map():
    pages = tuple(PageRecord(f"p{i}", f"Page {i}", "concept", f"concepts/p{i}.md", None,
                             f"Summary {i}", (ContentBlock(f"p{i}:0", f"p{i}", None, f"Body {i}", 0),), (), f"h{i}", 6, None)
                  for i in range(2))
    snapshot = WikiSnapshot("snap", str(Path("/tmp/wiki")), "v2", pages, ())

    class Mapper:
        async def complete(self, messages, **kwargs):
            return type("Response", (), {"content": "{\"v001-c001\": [\"p0\"], \"null\": [\"p1\"]}"})()

    outline = asyncio.run(plan_theme_outline(theme="网文写作", purpose="", provider=OutlineProvider()))
    runtime = asyncio.run(place_page_summaries(outline, snapshot, Mapper(), batch_size=2))
    assert runtime["volumes"][0]["chapters"][0]["page_ids"] == ["p0"]


def test_strict_theme_outline_does_not_create_fallback_chapter():
    pages = tuple(PageRecord(f"p{i}", f"Page {i}", "concept", f"concepts/p{i}.md", None,
                             f"Summary {i}", (ContentBlock(f"p{i}:0", f"p{i}", None, f"Body {i}", 0),), (), f"h{i}", 6, None)
                  for i in range(2))
    snapshot = WikiSnapshot("snap", str(Path("/tmp/wiki")), "v2", pages, ())

    class Mapper:
        async def complete(self, messages, **kwargs):
            return type("Response", (), {"content": "{\"assignments\": []}"})()

    outline = asyncio.run(plan_theme_outline(theme="网文写作", purpose="", provider=OutlineProvider()))
    outline["strict_chapter_count"] = 2
    runtime = asyncio.run(place_page_summaries(outline, snapshot, Mapper(), batch_size=2))
    assert all(v["volume_id"] != "v999" for v in runtime["volumes"])


def test_build_from_wiki_can_consume_theme_outline(tmp_path):
    project = tmp_path / "project"
    project.mkdir(parents=True)
    (project / "book.rules.md").write_text(
        "# Book rules\n\n- Preserve source meaning.\n", encoding="utf-8"
    )
    (project / ".llm-wiki").mkdir(parents=True)
    (project / ".llm-wiki" / "project.json").write_text('{"schema_version":"v2.0"}', encoding="utf-8")
    (project / ".llm-wiki" / "policy.json").write_text('{"external_llm_allowed":true}', encoding="utf-8")
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
