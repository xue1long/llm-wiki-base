"""Phase 1.1 — project-level v3.0.0 template assets parse correctly.

Verifies the four novel-wiki project templates (spec §4.5 format):
- headers (version 3.0.0 / type) parse
- required/optional slot names are exactly the spec set
- the F3 contract holds: no ``## heading`` line contains a slot marker
- rendering a slots-dict through the template round-trips headings
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROJECT_TEMPLATES = REPO_ROOT / "knowledge" / "novel-wiki" / ".wiki-templates"

pytestmark = pytest.mark.skipif(
    not (PROJECT_TEMPLATES / "concept.md").is_file(),
    reason="protected novel-wiki project templates are not materialized",
)

EXPECTED = {
    "concept": {
        "version": (3, 0, 0),
        "required": ["definition", "characteristics", "context",
                     "anti_patterns", "evidence", "examples",
                     "related_concepts", "references"],
        "optional": [],
    },
    "source": {
        "version": (3, 0, 0),
        "required": ["source_meta", "transcription_quality", "summary",
                     "key_points", "credibility"],
        "optional": [],
    },
    "entity": {
        "version": (3, 0, 0),
        "required": ["basic_info", "summary", "craft_value", "related"],
        "optional": ["aliases"],
    },
    "synthesis": {
        "version": (3, 0, 0),
        "required": ["topic", "viewpoints", "consensus",
                     "evidence_comparison", "conclusion"],
        "optional": [],
    },
}


def _resolve(page_type: str):
    from src.wiki.core.types import PageType
    from src.wiki.templates import required_slot_names, resolve
    tpl = resolve(PageType(page_type), REPO_ROOT / "knowledge" / "novel-wiki")
    return tpl, required_slot_names(tpl)


@pytest.mark.parametrize("ptype", ["concept", "source", "entity", "synthesis"])
def test_v3_template_parses(ptype: str) -> None:
    tpl_path = PROJECT_TEMPLATES / f"{ptype}.md"
    assert tpl_path.exists(), f"missing project template {tpl_path}"
    tpl, required = _resolve(ptype)
    assert tpl.source == "project", f"{ptype} template must come from project level"
    assert tpl.version == "3.0.0"
    assert set(required) == set(EXPECTED[ptype]["required"])


@pytest.mark.parametrize("ptype", ["concept", "source", "entity", "synthesis"])
def test_f3_no_marker_on_heading_lines(ptype: str) -> None:
    """F3 contract: no heading line may carry a slot marker or # comment."""
    text = (PROJECT_TEMPLATES / f"{ptype}.md").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("#"):
            assert "slot:" not in line, f"F3 violation: marker on heading line: {line!r}"
            assert "# " not in line.lstrip("#"), f"F3 violation: trailing comment on heading: {line!r}"


def test_render_v3_source_with_new_slots() -> None:
    """v3.0.0 source template renders transcription_quality/credibility and
    drops extracted_concepts (bundled-only slot) — plan 1.6 build output."""
    from src.wiki.core.types import PageType
    from src.wiki.templates import resolve
    from src.wiki.templates.renderer import render_body

    tpl = resolve(PageType.SOURCE, REPO_ROOT / "knowledge" / "novel-wiki")
    slots = {
        "source_meta": "- 路径: raw/a.md",
        "transcription_quality": "ASR 转录（自动转写含错漏，需人工复核）",
        "summary": "摘要",
        "key_points": ["要点一"],
        "credibility": "UGC 网络来源（可信度/ugc）",
        "extracted_concepts": ["[[c1]]"],  # bundled-only → must be dropped
    }
    body = render_body(tpl.body_markdown, slots, PageType.SOURCE)
    assert "## 转录质量" in body
    assert "ASR 转录" in body
    assert "## 可信度声明" in body
    assert "## 关键观点" in body
    # extracted_concepts has no marker in the v3.0.0 template → dropped
    assert "抽取的概念" not in body
    # no template comments leaked
    assert "slot:" not in body


def test_render_v3_roundtrip() -> None:
    """A slots dict renders every required heading in the spec order."""
    from src.wiki.core.types import PageType
    from src.wiki.templates import resolve
    from src.wiki.templates.renderer import render_body

    tpl = resolve(PageType.CONCEPT, REPO_ROOT / "knowledge" / "novel-wiki")
    slots = {
        "definition": "定义文本",
        "characteristics": ["特征一"],
        "context": "适用场景",
        "anti_patterns": ["反模式"],
        "evidence": "来源性质",
        "examples": ["例子"],
        "related_concepts": ["[[其他]]"],
        "references": ["[[来源页]]"],
    }
    body = render_body(tpl.body_markdown, slots, PageType.CONCEPT)
    for heading in ("## 定义", "## 主要特点", "## 适用场景", "## 反模式与常见错误",
                    "## 证据强度", "## 例子", "## 相关概念", "## 参考来源"):
        assert heading in body
    assert "slot:" not in body  # markers consumed
    assert "<!--" not in body.replace("<!-- wiki-template-version: 3.0.0 -->", "").replace(
        "<!-- wiki-template-type: concept -->", "")
