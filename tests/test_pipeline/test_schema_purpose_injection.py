"""Phase 2.1 — novel-wiki 场景模板 schema/purpose/taxonomy 落盘 + 注入链路测试。

Spec §4.1–4.4（docs/superpowers/specs/2026-08-15-novel-wiki-writing-template-design.md）
要求 four project-root assets 落盘在 knowledge/novel-wiki/：

- schema.md（§4.1）：4 内置类型 + 写作域 Conventions，无自定义类型
- purpose.md（§4.2）：写作域改写（可检索/可执行/可证伪 + Key Questions）
- taxonomy.md（§4.3）：受控分类轴（写作技法/题材体系/平台规则/读者与市场/案例与素材/心态与职业）
- taxonomy_tags.md（§4.4，独立文件）：tags 枚举（情绪/场景阶段/读者群/平台 等前缀与值）

验收标准：
1. 四个资产文件真实存在且非空（资产落盘）。
2. taxonomy.md strict 冒烟解析通过（O5：防空/损坏静默放行）。
3. schema.md 可被 SchemaRegistry 解析且无自定义类型（保持 4 内置）。
4. taxonomy_tags.md 文档化 §4.4 前缀枚举（含 读者群/ 平台/ 新增前缀）。
5. 注入链路：generate_ingest 从 project-root 重读 schema/purpose/taxonomy 并
   注入 LLM 提示词（沿用 test_unified_generate_injects_wiki_purpose /
   test_analyze_injects_project_taxonomy 模式）。
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tests.support.test_helpers import ScriptedLLMProvider
from src.wiki.core.paths import WikiPaths
from src.wiki.storage.ensure import ensure_knowledge_base

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
NOVEL_WIKI = REPO_ROOT / "knowledge" / "novel-wiki"

ASSET_NAMES = ("schema.md", "purpose.md", "taxonomy.md", "taxonomy_tags.md")


@pytest.fixture(autouse=True)
def _use_legacy_pipeline_for_compatibility_tests(monkeypatch):
    monkeypatch.setenv("RUFLO_PIPELINE_MODE", "legacy")

# 与 spec §4.3 分类轴一致
EXPECTED_CATEGORIES = {
    "写作技法": {"选题与立意", "大纲与结构", "开篇与黄金三章", "人物塑造", "情节与冲突",
               "爽点与情绪", "节奏与悬念", "文笔与语言", "对话与描写", "世界观设定", "修改与打磨"},
    "题材体系": {"玄幻", "仙侠", "都市", "科幻", "悬疑推理", "历史军事", "游戏竞技",
               "女频现言", "女频古言", "女频玄幻", "流派变体"},
    "平台规则": {"签约", "上架", "全勤与福利", "推荐与曝光", "审核与合规", "版权与运营"},
    "读者与市场": {"读者心态", "市场趋势", "数据分析", "作者运营"},
    "案例与素材": {"作品案例", "片段与金句", "桥段与梗", "诗词素材"},
    "心态与职业": {"写作心态", "习惯与方法", "职业规划"},
}


# ---------------------------------------------------------------------------
# 1. 资产落盘
# ---------------------------------------------------------------------------


def test_scene_asset_files_landed() -> None:
    """四个 project-root 资产文件必须存在且非空。"""
    for name in ASSET_NAMES:
        path = NOVEL_WIKI / name
        assert path.is_file(), f"missing asset: {path}"
        assert path.read_text(encoding="utf-8").strip(), f"empty asset: {path}"


def test_taxonomy_strict_parse_passes() -> None:
    """O5 冒烟：taxonomy.md strict 解析必须通过（防空/损坏静默放行）。"""
    from src.wiki.taxonomy_registry import TaxonomyRegistry

    registry = TaxonomyRegistry.from_project(NOVEL_WIKI, strict=True)
    assert not registry.errors
    assert registry.categories.keys() == set(EXPECTED_CATEGORIES), (
        f"taxonomy categories mismatch: {sorted(registry.categories)}"
    )
    for cat, items in EXPECTED_CATEGORIES.items():
        assert items.issubset(set(registry.categories[cat])), f"{cat} missing items"
    # 校验能正确判定（写时门禁依赖）
    assert registry.validate("写作技法", "人物塑造") == []
    assert registry.validate("写作技法", "不存在的分类值")


def test_schema_parses_without_custom_types() -> None:
    """§4.1：schema.md 保持 4 内置类型，不声明自定义类型。"""
    from src.wiki.schema_registry import SchemaRegistry

    registry = SchemaRegistry.from_project(NOVEL_WIKI)
    assert registry.all_custom_type_names() == []
    # 页面类型表只声明 4 内置类（PageType 枚举本身含 8 个历史值，schema.md 不新增）
    schema_text = (NOVEL_WIKI / "schema.md").read_text(encoding="utf-8")
    for builtin in ("source", "entity", "concept", "synthesis"):
        assert f"| {builtin} |" in schema_text, f"schema.md missing type row: {builtin}"


def test_purpose_content_writing_domain() -> None:
    """§4.2：purpose.md 含写作域目标标记（可检索/可执行/可证伪 + procedure 优先）。"""
    text = (NOVEL_WIKI / "purpose.md").read_text(encoding="utf-8")
    for marker in ("可检索、可执行、可证伪", "Key Questions", "procedure 优先"):
        assert marker in text, f"purpose.md missing marker: {marker!r}"


def test_taxonomy_tags_documents_prefix_enumeration() -> None:
    """§4.4：taxonomy_tags.md 文档化前缀枚举（含 读者群/ 平台/ 新增）。"""
    text = (NOVEL_WIKI / "taxonomy_tags.md").read_text(encoding="utf-8")
    for prefix in ("情绪/", "场景阶段/", "读者群/", "平台/"):
        assert prefix in text, f"taxonomy_tags.md missing prefix: {prefix!r}"
    for value in ("男频", "女频", "全年龄", "起点", "番茄", "晋江"):
        assert value in text, f"taxonomy_tags.md missing value: {value!r}"


# ---------------------------------------------------------------------------
# 2. 注入链路：generate_ingest 重读 project-root schema/purpose/taxonomy
# ---------------------------------------------------------------------------


# 沿用 test_ingest_generate_commit_split.py 的 unified-path 脚本形态
_CONCEPT_SCRIPT = [
    {
        "pages": [
            {
                "id": "c1",
                "type": "concept",
                "title": "概念一",
                "slots": {
                    "definition": "这是一个用于测试的概念定义，内容足够长。",
                    "characteristics": ["特征一", "特征二"],
                    "examples": ["示例一"],
                    "related_concepts": [],
                    "references": [],
                },
            },
        ],
    },
]


@pytest.mark.asyncio
async def test_generate_ingest_injects_project_root_texts(tmp_path: Path) -> None:
    """注入链路：project-root 的 schema/purpose/taxonomy 必须进入 LLM 提示词。

    用真实 novel-wiki 资产填充 tmp 项目，跑 generate_ingest，断言首个调用
    的 prompt 包含 schema.md 文本、purpose.md 文本与 taxonomy 注入文本。
    """
    # 拷贝真实资产到 tmp 项目根（复用 1.1 注入口径，防止两套文本漂移）
    for name in ASSET_NAMES[:3]:  # schema/purpose/taxonomy
        shutil.copy(NOVEL_WIKI / name, tmp_path / name)
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    raw = paths.raw_sources / "src.md"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("源文档内容。", encoding="utf-8")

    provider = ScriptedLLMProvider([dict(x) for x in _CONCEPT_SCRIPT])

    from src.pipeline.ingest import generate_ingest

    pages, _extra, _meta = await generate_ingest(
        paths=paths,
        source_path=raw,
        source_text="源文档内容。",
        provider=provider,
        task_id="kb-schema-purpose-injection",
    )
    assert pages, "generate_ingest must produce pages"

    # 第一个调用 = unified prompt（PURPOSE_SECTION/TAXONOMY_SECTION/SCHEMA_SECTION）
    first = provider.calls[0]
    prompt = str(first.get("messages", first))
    purpose_text = (tmp_path / "purpose.md").read_text(encoding="utf-8")
    taxonomy_text = (tmp_path / "taxonomy.md").read_text(encoding="utf-8")
    schema_text = (tmp_path / "schema.md").read_text(encoding="utf-8")

    # 关键标记抽查（避免整段断言被 prompt 包装格式影响）
    assert "可检索、可执行、可证伪" in prompt, "purpose 文本未注入提示词"
    assert "写作技法" in prompt and "人物塑造" in prompt, "taxonomy 分类未注入提示词"
    assert "Page Types" in prompt or "wiki/sources" in prompt, "schema 文本未注入提示词"

    # 落盘资产必须与注入内容一致（拷贝即一致；此处锁定非占位）
    assert purpose_text.strip() != "(未配置)"
    assert taxonomy_text.strip() != "(未配置)"
    assert schema_text.strip() != "(未配置)"
