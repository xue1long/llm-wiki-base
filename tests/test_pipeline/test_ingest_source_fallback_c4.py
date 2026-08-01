"""C4 regression: the missing-template fallback source body must NOT embed the
full raw text in a ``## 正文内容`` section.

The source-page template (``src/wiki/templates/bundled/source.md``) carries
summary + metadata only — full text lives in ``raw/``. The hardcoded fallback
used when the template is missing (operator deleted the bundled file) must
match that contract: a distilled body without the full-text section, or lint
flags it LINT-RAW-PASTE (see tests/test_wiki/test_lint.py).
"""
from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from src.pipeline.ingest import generate_ingest
from src.shared.test_helpers import ScriptedLLMProvider
from src.wiki.core.paths import WikiPaths
from src.wiki.core.types import PageType
from src.wiki.storage.ensure import ensure_knowledge_base

_FULL_TEXT = "这是完整的原始文档正文内容，绝不应被内嵌到 source 页的蒸馏正文中。" * 10

# A unified-path LLM script that produces one concept page (no source page),
# so Fix D appends the deterministic source page whose body we inspect.
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
async def test_source_fallback_omits_fulltext_section(tmp_path: Path, caplog) -> None:
    """When the source.md template is missing, the fallback body is distilled:
    no ``## 正文内容`` heading, no raw source text embedded; the summary /
    key_points / extracted_concepts sections are still present; an ERROR is
    logged for the missing template."""
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    raw = paths.raw_sources / "c4-fallback.md"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text(_FULL_TEXT, encoding="utf-8")

    provider = ScriptedLLMProvider([dict(x) for x in _CONCEPT_SCRIPT])

    # `generate_ingest` imports `resolve` inside the function via
    # `from ..wiki.templates import resolve as resolve_template`, so we patch
    # the package re-export. The generator uses `list_resolved` (which calls
    # the *resolver-module* `resolve` directly, unaffected by this patch), so
    # only the source-template lookup in generate_ingest raises.
    import src.wiki.templates as templates_mod

    real_resolve = templates_mod.resolve

    def _no_source_template(page_type, project_root):
        if page_type == PageType.SOURCE:
            raise FileNotFoundError("source.md template missing")
        return real_resolve(page_type, project_root)

    with caplog.at_level(logging.ERROR, logger="src.pipeline.ingest"):
        with patch.object(
            templates_mod,
            "resolve",
            side_effect=_no_source_template,
        ):
            pages, _extra_pages, _meta = await generate_ingest(
                paths=paths,
                source_path=raw,
                source_text=_FULL_TEXT,
                provider=provider,
                task_id="kb-c4",
            )

    source = next(p for p in pages if p.type == PageType.SOURCE)
    # C4: no full-text section, no raw text embedded.
    assert "## 正文内容" not in source.body
    assert _FULL_TEXT not in source.body
    # Distilled sections are still present.
    assert "## 摘要" in source.body
    assert "## 关键观点" in source.body
    assert "## 抽取的概念" in source.body
    # The missing template was surfaced as an ERROR log.
    assert any(r.levelname == "ERROR" for r in caplog.records), (
        "missing template must log an ERROR"
    )
