# tests/test_pipeline/test_generator.py
import pytest
from src.shared.test_helpers import ScriptedLLMProvider
from src.pipeline.schemas import AnalysisResult, EntityMention, PageSpec
from src.pipeline.generator import generate, PROCESSING_DEPTH_VALUES
from src.wiki.core.types import PageType


def test_processing_depth_values_include_operation():
    """PROCESSING_DEPTH_VALUES must equal ['concept', 'memory'] and never
    absorb page-type names (regression: the LLM response schema used to mix
    page-type names into the processing_depth enum, inviting illegal values
    from the model). 'concept' is the one page type that doubles as a valid
    depth, so the guard is against every OTHER PageType value."""
    assert PROCESSING_DEPTH_VALUES == ["concept", "memory", "operation"]
    non_depth_page_types = {t.value for t in PageType} - {"concept"}
    assert not (set(PROCESSING_DEPTH_VALUES) & non_depth_page_types), (
        "PROCESSING_DEPTH_VALUES must not contain page-type names other than "
        "the valid depth 'concept'"
    )


def test_clean_placeholder_text_scrubs_lint_flagged_substrings():
    """Phase 3 follow-up (M4)：渲染后清洗必须移除 lint 占位符子串。

    即使 prompt 已引导 LLM 不用「来源未提供具体例子」，模型仍可能惯性输出
    该 fallback——清洗兜底保证新产出不触发 LINT-PLACEHOLDER。替换文本自身
    不得包含 lint _PLACEHOLDER_SUBSTRINGS 的任何子串（（系统占位 / 待补充 /
    见下游概念页 / 来源未提供具体例子）。
    """
    from src.pipeline.generator import _clean_placeholder_text, _PLACEHOLDER_CLEANUPS

    body = (
        "## 例子\n\n- 来源未提供具体例子\n\n"
        "## 证据强度\n\n来源未提供例子，但……\n\n"
        "（系统占位：此项由系统补齐，请人工补充）\n"
    )
    cleaned = _clean_placeholder_text(body)
    for bad in ("来源未提供具体例子", "来源未提供例子", "（系统占位"):
        assert bad not in cleaned, f"placeholder {bad!r} must be scrubbed"
    # 替换文本自身不引入新的 lint 占位符子串
    lint_subs = ("（系统占位", "待补充", "见下游概念页", "来源未提供具体例子")
    for old, new in _PLACEHOLDER_CLEANUPS:
        for sub in lint_subs:
            assert sub not in new, f"replacement {new!r} contains lint substring {sub!r}"


def test_clean_placeholder_text_scrubs_daibuchong_and_jianguyou():
    """Phase 4 batch 1 实测新增：LLM 惯性输出「待补充」「见下游概念页」也是
    高频 lint 占位符（扩句法/切割法/曲折法 三个页被 LINT-PLACEHOLDER 拦）。
    清洗兜底必须覆盖它们，替换文本不得含占位符子串。"""
    from src.pipeline.generator import (
        _clean_placeholder_text, _PLACEHOLDER_CLEANUPS,
    )

    body = (
        "## 定义\n\n该方法可用于待补充的内容。\n\n"
        "## 证据\n\n见下游概念页懆述。\n"
    )
    cleaned = _clean_placeholder_text(body)
    for bad in ("待补充", "见下游概念页"):
        assert bad not in cleaned, f"placeholder {bad!r} must be scrubbed"
    # 替换文本不得引入 lint 占位符子串
    lint_subs = ("（系统占位", "待补充", "见下游概念页", "来源未提供具体例子")
    for old, new in _PLACEHOLDER_CLEANUPS:
        for sub in lint_subs:
            assert sub not in new, f"replacement {new!r} contains lint substring {sub!r}"


@pytest.mark.asyncio
async def test_generate_returns_pages(tmp_path):
    from src.wiki.storage.ensure import ensure_knowledge_base
    ensure_knowledge_base(tmp_path)
    from src.wiki.core.paths import WikiPaths
    paths = WikiPaths(tmp_path)

    analysis = AnalysisResult(
        task_id="kb-1", source_path="raw/sources/x.pdf",
        summary="Article summary.",
        entities=[EntityMention(name="Backprop", slug="backprop", type="concept", context="...", confidence=0.9)],
        suggested_pages=[
            PageSpec(type="source", slug="kb-1", title="Article", reasoning="source page"),
            PageSpec(type="concept", slug="backprop", title="Backprop", reasoning="concept page"),
        ],
    )

    provider = ScriptedLLMProvider([
        {"pages": [
            {"id": "kb-1", "type": "source", "title": "Article",
             "frontmatter_extra": {"tags": ["concept"]},
             "slots": {"source_meta": "sm", "summary": "Article body",
                       "key_points": ["kp"], "extracted_concepts": ["c"]}},
            {"id": "backprop", "type": "concept", "title": "Backprop",
             "frontmatter_extra": {"tags": []},
             "slots": {"definition": "Backprop body",
                       "characteristics": ["c1"], "examples": ["e1"],
                       "related_concepts": ["rc"], "references": ["r"]}},
        ]}
    ])

    pages = await generate(
        paths=paths,
        analysis=analysis,
        existing_wiki_index="",
        provider=provider,
    )
    assert len(pages) == 2
    assert pages[0].id == "article"  # slug from title, not LLM's id
    assert pages[0].type == PageType.SOURCE
    assert pages[1].id == "backprop"
    assert pages[1].type == PageType.CONCEPT


@pytest.mark.asyncio
async def test_generate_emits_relations(tmp_path):
    """Generator populates WikiPage.relations from LLM response."""
    from src.wiki.storage.ensure import ensure_knowledge_base
    from src.wiki.core.paths import WikiPaths
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)

    analysis = AnalysisResult(
        task_id="kb-1", source_path="raw/sources/x.pdf", summary="S",
        suggested_pages=[PageSpec(type="source", slug="kb-1", title="T", reasoning="r")],
    )
    provider = ScriptedLLMProvider([
        {"pages": [
            {"id": "kb-1", "type": "source", "title": "T",
             "frontmatter_extra": {},
             "slots": {"source_meta": "sm", "summary": "B",
                       "key_points": ["B"], "extracted_concepts": ["B"]},
             "relations": [{"target": "other", "type": "references", "weight": 0.8}]},
        ]}
    ])
    pages = await generate(paths=paths, analysis=analysis, existing_wiki_index="", provider=provider)
    assert len(pages) == 1
    assert len(pages[0].relations) == 1
    assert pages[0].relations[0].target_id == "other"
    assert pages[0].relations[0].type == "references"


@pytest.mark.asyncio
async def test_generate_forwards_v22_fields_from_suggested_pages(tmp_path):
    """Generator passes grade/processing_depth/is_immutable from each
    suggested_page dict through to the constructed WikiPage."""
    from src.wiki.storage.ensure import ensure_knowledge_base
    from src.wiki.core.paths import WikiPaths
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)

    analysis = AnalysisResult(
        task_id="kb-1", source_path="raw/sources/x.pdf", summary="S",
        suggested_pages=[
            PageSpec(type="source", slug="kb-1", title="Article", reasoning="r",
                     grade="A", processing_depth="memory", is_immutable=True),
        ],
    )
    provider = ScriptedLLMProvider([
        {"pages": [
            {"id": "kb-1", "type": "source", "title": "Article",
             "grade": "A", "processing_depth": "memory", "is_immutable": True,
             "slots": {"source_meta": "sm", "summary": "B",
                       "key_points": ["B"], "extracted_concepts": ["B"]}},
        ]}
    ])
    pages = await generate(paths=paths, analysis=analysis, existing_wiki_index="", provider=provider)
    assert len(pages) == 1
    assert pages[0].grade == "A"
    assert pages[0].processing_depth == "memory"
    assert pages[0].is_immutable is True


@pytest.mark.asyncio
async def test_generate_uses_v22_defaults_when_missing(tmp_path):
    """When the LLM response omits grade/processing_depth/is_immutable,
    the constructed WikiPage gets defaults inferred from its PageType (B / source / False).
    """
    from src.wiki.storage.ensure import ensure_knowledge_base
    from src.wiki.core.paths import WikiPaths
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)

    analysis = AnalysisResult(
        task_id="kb-1", source_path="raw/sources/x.pdf", summary="S",
        suggested_pages=[PageSpec(type="source", slug="kb-1", title="T", reasoning="r")],
    )
    provider = ScriptedLLMProvider([
        {"pages": [
            {"id": "kb-1", "type": "source", "title": "T",
             "slots": {"source_meta": "sm", "summary": "B",
                       "key_points": ["B"], "extracted_concepts": ["B"]}},
        ]}
    ])
    pages = await generate(paths=paths, analysis=analysis, existing_wiki_index="", provider=provider)
    assert len(pages) == 1
    assert pages[0].grade == "B"
    assert pages[0].processing_depth == "source"
    assert pages[0].is_immutable is False


# ---------------------------------------------------------------------------
# O-7: _render_template_section uses render_for_prompt() (compact + optional
# annotations) instead of dumping raw body_markdown
# ---------------------------------------------------------------------------

def test_render_template_section_compact_with_optional_annotations(tmp_path):
    """Prompt section uses render_for_prompt() — compact + optional annotations.

    Regression guard for the O-7 refactor: previously the generator
    dumped each template's raw body_markdown into the prompt (verbose,
    no hint about which sections are optional). After O-7 it routes
    through render_for_prompt() which annotates optional slots.
    """
    from src.pipeline.generator import _render_template_section

    # `tmp_path` is a fresh project root with no overrides → bundled
    # templates apply. The bundled entity template has `<!-- slot:aliases? -->`
    # which render_for_prompt() marks with `_(optional)_`.
    out = _render_template_section(tmp_path)
    assert "### entity" in out
    assert "<!-- slot:aliases? -->  _(optional)_" in out
    # Bundled concept template has no optional slots — must NOT be annotated
    assert "<!-- slot:definition -->" in out
    # The render-for-prompt path is compact: no blank line between
    # heading and its slot markers.
    assert "## 定义\n<!-- slot:definition -->" in out


def test_render_template_section_includes_operation_template(tmp_path):
    """Operation depth is represented by a separate, non-PageType template."""
    from src.pipeline.generator import _render_operation_template_section

    out = _render_operation_template_section(tmp_path)

    assert "### operation" in out
    assert "<!-- slot:steps -->" in out
    assert "<!-- slot:verification -->" in out


def test_render_template_section_falls_back_when_no_bundled(tmp_path, monkeypatch):
    """When list_resolved() raises, the section reports 'no templates available'.

    The generator imports list_resolved lazily inside the function body,
    so we patch the source module (src.wiki.templates.list_resolved)
    rather than a name in src.pipeline.generator's namespace.
    """
    from src.pipeline.generator import _render_template_section

    def _raise(*_a, **_k):
        raise RuntimeError("simulated bundled dir missing")

    monkeypatch.setattr("src.wiki.templates.list_resolved", _raise)
    out = _render_template_section(tmp_path)
    assert "no templates available" in out.lower()


# ---------------------------------------------------------------------------
# Regression: GENERATOR_PROMPT must forbid placeholder fillers like "..."
# that were observed in production when the LLM had no content for a
# required template slot (novel-wiki kb-20260726100503, 7 pages with
# body = "..."). The prompt previously said "Do NOT omit sections" with
# no exception for "no content" — pushing the LLM into a must-emit
# dead end where it produced the smallest possible filler.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generator_prompt_prohibits_ellipsis_filler(tmp_path):
    """GENERATOR_PROMPT must (a) explicitly forbid '...' as a body filler
    and (b) allow OMITting a section when there's no substantive content
    for it.
    """
    from src.wiki.storage.ensure import ensure_knowledge_base
    from src.wiki.core.paths import WikiPaths
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)

    analysis = AnalysisResult(
        task_id="kb-1", source_path="raw/sources/x.pdf", summary="S",
        suggested_pages=[
            PageSpec(type="concept", slug="kb-1", title="T", reasoning="r"),
        ],
    )
    provider = ScriptedLLMProvider([{
        "pages": [
            {"id": "kb-1", "type": "concept", "title": "T",
             "slots": {"definition": "B",
                       "characteristics": ["B"], "examples": ["B"],
                       "related_concepts": ["B"], "references": ["B"]}},
        ]
    }])
    await generate(
        paths=paths, analysis=analysis, existing_wiki_index="",
        provider=provider,
    )

    # Generator calls provider.complete(messages=[...]) — content is the
    # full prompt string assembled from GENERATOR_PROMPT + analysis_json.
    assert provider.calls, "expected at least one LLM call"
    call = provider.calls[0]
    msgs = call.get("messages") or []
    assert msgs and msgs[0].get("role") == "user"
    prompt = msgs[0]["content"]

    # (a) some kind of prohibition on '...' as a filler.
    # Accept any directive language; require prohibition keyword near '...'
    found_ellipsis_forbid = False
    for line in prompt.splitlines():
        if "..." not in line:
            continue
        line_lower = line.lower()
        if any(kw in line_lower for kw in (
            "never", "don't", "do not", "forbid", "禁止", "不要",
            "avoid", "never use",
        )):
            found_ellipsis_forbid = True
            break
    assert found_ellipsis_forbid, (
        "GENERATOR_PROMPT must include a directive forbidding '...' as "
        "a filler (production regression on novel-wiki 2026-07-26: 7 pages "
        "shipped with body=\"...\")."
    )

    # (b) OMIT sections is permitted when content is insufficient.
    # Long prompt paragraphs may wrap across many lines, so check the
    # whole prompt for both the OMIT permission AND a content-conditional
    # ("no content", "no substantive", "insufficient", "have nothing", "lacks").
    prompt_lower = prompt.lower()
    has_omit_permission = "omit" in prompt_lower
    has_content_condition = any(
        cond in prompt_lower for cond in (
            "no substantive", "no content", "insufficient",
            "have nothing", "lacks", "缺", "不写",
        )
    )
    assert has_omit_permission, (
        "GENERATOR_PROMPT must mention OMIT permission for sections."
    )
    assert has_content_condition, (
        "GENERATOR_PROMPT must pair the OMIT permission with a "
        "no-content / no-substantive condition."
    )


# ---------------------------------------------------------------------------
# Borrowed from llm_wiki-main's buildGenerationPrompt:
#   - Anti-CoT directive (avoid `` leak into body)
#   - Subject-boundary guard (do NOT transfer claims between entities)
#   - Re-asserted language directive at the END of the prompt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generator_prompt_prohibits_chain_of_thought(tmp_path):
    """GENERATOR_PROMPT must explicitly forbid chain-of-thought /
    hidden reasoning. Defense against DeepSeek-style `` blocks leaking
    into wiki bodies and contravariant reasoning traces in markdown.
    """
    from src.wiki.storage.ensure import ensure_knowledge_base
    from src.wiki.core.paths import WikiPaths
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)

    analysis = AnalysisResult(
        task_id="kb-1", source_path="raw/sources/x.pdf", summary="S",
        suggested_pages=[
            PageSpec(type="concept", slug="kb-1", title="T", reasoning="r"),
        ],
    )
    provider = ScriptedLLMProvider([{
        "pages": [
            {"id": "kb-1", "type": "concept", "title": "T",
             "slots": {"definition": "B",
                       "characteristics": ["B"], "examples": ["B"],
                       "related_concepts": ["B"], "references": ["B"]}},
        ]
    }])
    await generate(
        paths=paths, analysis=analysis, existing_wiki_index="",
        provider=provider,
    )

    prompt = provider.calls[0]["messages"][0]["content"]
    p_lower = prompt.lower()
    forbid_found = False
    for kw in ("chain-of-thought", "chain of thought", "hidden reasoning",
               "thinking transcript", "thinking", "reasoning trace"):
        if kw in p_lower:
            line_idx = p_lower.find(kw)
            start = max(0, line_idx - 80)
            ctx = p_lower[start:line_idx + len(kw) + 80]
            if any(p in ctx for p in (
                "do not", "don't", "never", "no ", "avoid", "禁止", "不要",
            )):
                forbid_found = True
                break
    assert forbid_found, (
        "GENERATOR_PROMPT must forbid chain-of-thought / hidden reasoning."
    )


@pytest.mark.asyncio
async def test_generator_prompt_directs_ugc_tagging(tmp_path):
    """GENERATOR_PROMPT must include MANDATORY_PAIRS tags as mandatory
    via TAG_NAMESPACE_RULES (P0.4: UGC pairs moved from hardcoded prompts
    to MANDATORY_PAIRS config, dynamically rendered by build_tag_prompt_section).
    """
    from src.wiki.storage.ensure import ensure_knowledge_base
    from src.wiki.core.paths import WikiPaths
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)

    analysis = AnalysisResult(
        task_id="kb-1", source_path="raw/sources/x.pdf", summary="S",
        suggested_pages=[
            PageSpec(type="concept", slug="kb-1", title="T", reasoning="r"),
        ],
    )
    provider = ScriptedLLMProvider([{
        "pages": [{"id": "kb-1", "type": "concept", "title": "T",
                    "slots": {"definition": "B",
                              "characteristics": ["B"], "examples": ["B"],
                              "related_concepts": ["B"], "references": ["B"]}}]
    }])
    await generate(
        paths=paths, analysis=analysis, existing_wiki_index="",
        provider=provider,
    )

    prompt = provider.calls[0]["messages"][0]["content"]
    assert "素材/ugc" in prompt, (
        "GENERATOR_PROMPT must include 素材/ugc via TAG_NAMESPACE_RULES"
    )
    assert "可信度/ugc" in prompt, (
        "GENERATOR_PROMPT must include 可信度/ugc via TAG_NAMESPACE_RULES"
    )
    assert "Mandatory tags" in prompt, (
        "GENERATOR_PROMPT must include Mandatory tags section from build_tag_prompt_section"
    )


@pytest.mark.asyncio
async def test_generator_prompt_has_subject_boundary_guard(tmp_path):
    """GENERATOR_PROMPT must tell the LLM not to transfer claims,
    evaluations, or recommendations between subjects simply because
    they share keywords. Borrowed from llm_wiki-main's
    `buildGenerationPrompt` (subject-boundary guard).
    """
    from src.wiki.storage.ensure import ensure_knowledge_base
    from src.wiki.core.paths import WikiPaths
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)

    analysis = AnalysisResult(
        task_id="kb-1", source_path="raw/sources/x.pdf", summary="S",
        suggested_pages=[
            PageSpec(type="concept", slug="kb-1", title="T", reasoning="r"),
        ],
    )
    provider = ScriptedLLMProvider([{
        "pages": [{"id": "kb-1", "type": "concept", "title": "T",
                    "slots": {"source_meta": "sm", "summary": "B",
                       "key_points": ["B"], "extracted_concepts": ["B"]}}]
    }])
    await generate(
        paths=paths, analysis=analysis, existing_wiki_index="",
        provider=provider,
    )

    prompt = provider.calls[0]["messages"][0]["content"]
    p_lower = prompt.lower()
    # Must mention keeping claims bounded to subjects AND not transferring them.
    has_subject = any(
        term in p_lower for term in ("subject", "boundary", "boundaries")
    )
    has_claim_term = "claim" in p_lower or "evaluation" in p_lower
    has_no_transfer = any(
        phrase in p_lower for phrase in (
            "do not transfer", "don't transfer", "not transfer",
            "not be transferred", "do not merge", "don't merge",
            "do not generalize", "don't generalize",
            "不串", "不要把", "不要将",
        )
    )
    assert has_subject and has_claim_term and has_no_transfer, (
        "GENERATOR_PROMPT must include a subject-boundary guard: "
        "(1) mention subjects/boundaries, (2) talk about claims / evaluations, "
        "(3) forbid transferring them across subjects."
    )


@pytest.mark.asyncio
async def test_generator_prompt_repeats_language_directive_at_end(tmp_path):
    """The language directive must be re-asserted near the END of
    GENERATOR_PROMPT (not only the beginning) so it wins the
    'most-recent-instruction' tie-breaker for multi-page generation —
    borrowed from llm_wiki-main.
    """
    from src.wiki.storage.ensure import ensure_knowledge_base
    from src.wiki.core.paths import WikiPaths
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)

    analysis = AnalysisResult(
        task_id="kb-1", source_path="raw/sources/x.pdf", summary="S",
        suggested_pages=[
            PageSpec(type="concept", slug="kb-1", title="T", reasoning="r"),
        ],
    )
    provider = ScriptedLLMProvider([{
        "pages": [{"id": "kb-1", "type": "concept", "title": "T",
                    "slots": {"source_meta": "sm", "summary": "B",
                       "key_points": ["B"], "extracted_concepts": ["B"]}}]
    }])
    await generate(
        paths=paths, analysis=analysis, existing_wiki_index="",
        provider=provider,
    )

    prompt = provider.calls[0]["messages"][0]["content"]
    # Take the last 800 characters and look for a language-style directive.
    tail = prompt[-800:].lower()
    # Expect "language" near the end AND one of (中文 / chinese / cjk / pinyin).
    has_lang_keyword = "language" in tail
    has_lang_detail = any(
        term in tail for term in ("中文", "chinese", "cjk", "pinyin", "simplified")
    )
    assert has_lang_keyword and has_lang_detail, (
        "GENERATOR_PROMPT must re-assert the language directive near the "
        "end (last ~800 chars) to prevent LLM drift on multi-page output."
    )


@pytest.mark.asyncio
async def test_generator_prompt_directs_slug_reuse(tmp_path):
    """GENERATOR_PROMPT must tell the LLM to reuse existing slugs
    verbatim when emitting `[[wikilinks]]` and `relations[].target`,
    rather than inventing new pinyin transliterations.

    Production evidence (novel-wiki 2026-07-26): 10 broken wikilinks
    of which 6 stemmed from LLM emitting different slug variants
    in different ingests (e.g. ``qi-dai-gan`` vs
    ``qi-dai-gan-chuangzuo``, ``urban-xianxia-stream`` vs
    ``dushi-xianxia-liu``).

    The test requires the prompt to (a) instruct slug reuse AND
    (b) forbid invention of new variants, in a slug/wikilink/relation
    *context* — not just anywhere in the prompt. This guards against
    false positives from unrelated directives (e.g. the existing
    "Do not invent relation type names" line about the 17 built-in
    relation *types*, which is about something else entirely).
    """
    from src.wiki.storage.ensure import ensure_knowledge_base
    from src.wiki.core.paths import WikiPaths
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)

    analysis = AnalysisResult(
        task_id="kb-1", source_path="raw/sources/x.pdf", summary="S",
        suggested_pages=[
            PageSpec(type="concept", slug="kb-1", title="T", reasoning="r"),
        ],
    )
    provider = ScriptedLLMProvider([{
        "pages": [{"id": "kb-1", "type": "concept", "title": "T",
                    "slots": {"source_meta": "sm", "summary": "B",
                       "key_points": ["B"], "extracted_concepts": ["B"]}}]
    }])
    await generate(
        paths=paths, analysis=analysis, existing_wiki_index="",
        provider=provider,
    )

    prompt = provider.calls[0]["messages"][0]["content"]
    p_lower = prompt.lower()

    # Strict phrases — none of these appear in the original prompt:
    REUSE_PHRASES = (
        "reuse existing", "reuse the existing", "reuse the same",
        "verbatim", "copy the slug", "use the existing slug",
        "复用", "字面", "原样复用", "使用现有",
    )
    NOINVENT_PHRASES = (
        "do not invent new", "don't invent new",
        "do not introduce new", "must not invent",
        "must not introduce", "no new variant", "no new slug",
        "不要重新", "不要发明", "不要新建", "不要缩写", "不要拼新",
    )

    # Collect windows around slug/wikilink/relation context (400-char wide)
    # so we can assert the directive lives in a slug-relevant place.
    windows = []
    for kw in ("slug", "wikilink", "wikilinks", "relations", "[["):
        idx = 0
        while True:
            i = p_lower.find(kw, idx)
            if i < 0:
                break
            windows.append(p_lower[max(0, i - 200):i + 300])
            idx = i + 1

    has_reuse_in_ctx = any(p in w for w in windows for p in REUSE_PHRASES)
    has_noinv_in_ctx = any(p in w for w in windows for p in NOINVENT_PHRASES)

    assert has_reuse_in_ctx, (
        "GENERATOR_PROMPT must include a slug/wikilink/relation-context "
        f"directive to reuse existing slugs verbatim. Looked for any of "
        f"{REUSE_PHRASES} in windows around 'slug' / 'wikilink' / 'relations'."
    )
    assert has_noinv_in_ctx, (
        "GENERATOR_PROMPT must include a slug/wikilink/relation-context "
        f"directive to forbid inventing new slug variants. Looked for any "
        f"of {NOINVENT_PHRASES} in windows around 'slug' / 'wikilink' / 'relations'."
    )


# ---------------------------------------------------------------------------
# CJK cut-over (2026-07-26): slugs may now include Chinese characters
# directly. The original prompt forced pinyin transliteration on every
# Chinese concept, which caused slug drift + broken wikilinks. After
# the cut-over, the prompt must explicitly tell the LLM that CJK
# characters are first-class slug material.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generator_prompt_allows_cjk_in_slugs(tmp_path):
    """After the CJK cut-over, the language section that constrains
    slugs must explicitly allow CJK characters and stop forcing
    pinyin transliteration. The directive must appear in BOTH the
    opening `## Language` block AND the closing re-asserted block
    so it wins the 'most-recent-instruction' tie-breaker.
    """
    from src.wiki.storage.ensure import ensure_knowledge_base
    from src.wiki.core.paths import WikiPaths
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)

    analysis = AnalysisResult(
        task_id="kb-1", source_path="raw/sources/x.pdf", summary="S",
        suggested_pages=[
            PageSpec(type="concept", slug="kb-1", title="T", reasoning="r"),
        ],
    )
    provider = ScriptedLLMProvider([{
        "pages": [{"id": "kb-1", "type": "concept", "title": "T",
                    "slots": {"source_meta": "sm", "summary": "B",
                       "key_points": ["B"], "extracted_concepts": ["B"]}}]
    }])
    await generate(
        paths=paths, analysis=analysis, existing_wiki_index="",
        provider=provider,
    )

    prompt = provider.calls[0]["messages"][0]["content"]

    # 1) Must NOT carry over the old rule that forces pinyin. The
    # original was: "Slugs (id、relations[].target) 始终用 ASCII
    # (中文术语用拼音或英文翻译)".  We assert it is gone.
    assert "始终用 ASCII" not in prompt, (
        "GENERATOR_PROMPT still carries the pre-CJK-cut-over rule that "
        "forces slugs to ASCII pinyin. Update the language directives."
    )

    # 2) Must contain a slug-context phrase that explicitly allows
    # CJK characters in slugs, in AT LEAST one of the language blocks.
    ACCEPT_PHRASES = (
        # English variants
        "cjk in slug", "cjk characters in slug", "allow cjk",
        "may use cjk", "include cjk", "preserve the natural",
        "preserve the original chinese", "no need to transliterate",
        "use the natural chinese",
        # Chinese variants
        "可直接使用中文", "可以使用中文", "slug 可包含中文",
        "保留中文", "无需拼音转写", "不需要拼音", "中文术语可直接",
    )

    has_accept = any(phrase in prompt for phrase in ACCEPT_PHRASES)
    assert has_accept, (
        "GENERATOR_PROMPT must include a phrase that explicitly allows "
        f"CJK characters in slugs (CJK cut-over). Looked for any of "
        f"{ACCEPT_PHRASES}."
    )


# ---------------------------------------------------------------------------
# Plan 27 (wiki v2.3 schema) — slot-based body generation + retry + fallback.
# ---------------------------------------------------------------------------


def _concept_slots():
    return {
        "definition": "d",
        "characteristics": ["c1"],
        "examples": ["e1"],
        "related_concepts": ["rc"],
        "references": ["r"],
    }


def _source_slots():
    return {
        "source_meta": "sm",
        "summary": "s",
        "key_points": ["kp"],
        "extracted_concepts": ["c"],
        "main_content": "",   # system-filled, LLM leaves empty
    }


@pytest.mark.asyncio
async def test_generate_retry_fills_missing_slots(tmp_path, caplog):
    """First call is missing required slots → retry directive + 2nd call fills them."""
    from src.wiki.storage.ensure import ensure_knowledge_base
    from src.wiki.core.paths import WikiPaths
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)

    analysis = AnalysisResult(
        task_id="kb-1", source_path="raw/sources/x.pdf", summary="S",
        suggested_pages=[
            PageSpec(type="concept", slug="kb-1", title="T", reasoning="r"),
        ],
    )
    # First call missing 'characteristics' and 'examples'; retry fills them.
    provider = ScriptedLLMProvider([
        {"pages": [{"id": "kb-1", "type": "concept", "title": "T",
                    "slots": {"definition": "d",
                              "related_concepts": ["rc"], "references": ["r"]}}]},
        {"pages": [{"id": "kb-1", "type": "concept", "title": "T",
                    "slots": _concept_slots()}]},
    ])
    pages = await generate(
        paths=paths, analysis=analysis, existing_wiki_index="", provider=provider,
    )
    assert len(pages) == 1
    page = pages[0]
    # Body must include all required headings now.
    import re
    headings = re.findall(r"^## (.+)$", page.body, re.MULTILINE)
    for h in ["定义", "主要特点", "例子", "相关概念", "参考来源"]:
        assert h in headings, f"missing heading '{h}' in body:\n{page.body}"
    # The retry prompt is recognisable by the directive line.
    assert len(provider.calls) >= 2
    second_prompt = provider.calls[1]["messages"][0]["content"]
    assert "Retry" in second_prompt or "retry" in second_prompt
    assert "characteristics" in second_prompt
    assert "examples" in second_prompt


@pytest.mark.asyncio
async def test_generate_persistent_missing_uses_placeholder_and_warns(tmp_path, caplog):
    """Required slots still missing after retry → placeholder fills them + WARN log."""
    import logging
    from src.wiki.storage.ensure import ensure_knowledge_base
    from src.wiki.core.paths import WikiPaths
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)

    analysis = AnalysisResult(
        task_id="kb-1", source_path="raw/sources/x.pdf", summary="S",
        suggested_pages=[
            PageSpec(type="concept", slug="kb-1", title="T", reasoning="r"),
        ],
    )
    # Both responses missing 'characteristics' and 'examples' — fallback triggers.
    incomplete = {"pages": [{"id": "kb-1", "type": "concept", "title": "T",
                             "slots": {"definition": "d",
                                       "related_concepts": ["rc"], "references": ["r"]}}]}
    provider = ScriptedLLMProvider([incomplete, incomplete])

    caplog.set_level(logging.WARNING, logger="src.pipeline.generator")
    pages = await generate(
        paths=paths, analysis=analysis, existing_wiki_index="", provider=provider,
    )
    assert len(pages) == 1
    body = pages[0].body
    # Phase 3 修复：必填槽缺失不再填占位符（lint M4 ERROR），保留标题+空内容。
    assert "（系统占位" not in body, (
        "missing required slots must NOT be filled with the system placeholder "
        "(lint flags it as M4 ERROR)"
    )
    # All headings still present.
    import re
    headings = re.findall(r"^## (.+)$", body, re.MULTILINE)
    for h in ["定义", "主要特点", "例子", "相关概念", "参考来源"]:
        assert h in headings, f"missing heading '{h}' in body:\n{body}"
    # Operator sees a WARN log naming the missing slots.
    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("filled with placeholder" in r.getMessage() for r in warns), \
        [r.getMessage() for r in warns]


@pytest.mark.asyncio
async def test_generate_renders_body_from_slots_through_template(tmp_path):
    """generate() uses render_body on slots → produced body contains all template headings."""
    from src.wiki.storage.ensure import ensure_knowledge_base
    from src.wiki.core.paths import WikiPaths
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)

    analysis = AnalysisResult(
        task_id="kb-1", source_path="raw/sources/x.pdf", summary="S",
        suggested_pages=[
            PageSpec(type="source", slug="kb-1", title="T", reasoning="r"),
        ],
    )
    provider = ScriptedLLMProvider([{
        "pages": [{"id": "kb-1", "type": "source", "title": "T",
                    "slots": _source_slots()}],
    }])
    pages = await generate(
        paths=paths, analysis=analysis, existing_wiki_index="", provider=provider,
    )
    body = pages[0].body
    import re
    headings = set(re.findall(r"^## (.+)$", body, re.MULTILINE))
    assert {"来源元数据", "摘要", "关键观点", "抽取的概念"}.issubset(headings)
    # Slot content is in the body.
    assert "sm" in body      # source_meta
    assert "s" in body       # summary
    # No leftover markers.
    assert "<!-- slot:" not in body


@pytest.mark.asyncio
async def test_generate_schema_has_min_properties_and_additional_properties_false(tmp_path):
    """JSON schema enforces `slots` object (minProperties=1) with primitive value types."""
    from src.wiki.storage.ensure import ensure_knowledge_base
    from src.wiki.core.paths import WikiPaths
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)

    analysis = AnalysisResult(
        task_id="kb-1", source_path="raw/sources/x.pdf", summary="S",
        suggested_pages=[
            PageSpec(type="concept", slug="kb-1", title="T", reasoning="r"),
        ],
    )
    provider = ScriptedLLMProvider([{
        "pages": [{"id": "kb-1", "type": "concept", "title": "T",
                    "slots": _concept_slots()}],
    }])
    await generate(paths=paths, analysis=analysis, existing_wiki_index="",
                   provider=provider)
    schema = provider.calls[0]["schema"]
    slots_schema = schema["properties"]["pages"]["items"]["properties"]["slots"]
    assert slots_schema.get("minProperties") == 1
    # Schema is permissive about which keys appear (`additionalProperties`),
    # but each value is constrained to non-empty string at provider level.
    assert slots_schema.get("additionalProperties", {}).get("minLength") == 1
    # Required fields at the page level no longer include body_markdown.
    page_required = schema["properties"]["pages"]["items"]["required"]
    assert "slots" in page_required
    assert "body_markdown" not in page_required


@pytest.mark.asyncio
async def test_generate_prompt_includes_source_slug_map(tmp_path):
    """Fix B: source_slug_map is interpolated into the prompt so the LLM
    uses the exact on-disk slug (not a guess) when emitting
    ``[[wikilinks]]`` to source pages."""
    from src.wiki.storage.ensure import ensure_knowledge_base
    from src.wiki.core.paths import WikiPaths
    from src.pipeline.generator import generate

    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)

    analysis = AnalysisResult(
        task_id="kb-1", source_path="raw/sources/x.md", summary="S",
        suggested_pages=[
            PageSpec(type="source", slug="kb-1", title="T", reasoning="r"),
        ],
    )
    provider = ScriptedLLMProvider([{"pages": []}])
    src_map = {
        "E:/raw/sources/foo.md": "foo-{8hex}",
        "E:/raw/sources/bar.md": "bar-{8hex}",
    }
    await generate(
        paths=paths,
        analysis=analysis,
        existing_wiki_index="",
        provider=provider,
        source_slug_map=src_map,
    )
    prompt = provider.calls[0]["messages"][0]["content"]
    # Both raw and slug of the map must be present.
    assert "foo-{8hex}" in prompt, "slug 'foo-{8hex}' not in prompt"
    assert "bar-{8hex}" in prompt, "slug 'bar-{8hex}' not in prompt"
    # Header section must precede the listing.
    assert "## Source page ids for this run" in prompt
    # Source-page instruction must be explicit so the LLM doesn't guess.
    assert "EXACT slugs" in prompt


@pytest.mark.asyncio
async def test_generate_prompt_handles_empty_source_slug_map(tmp_path):
    """If source_slug_map is None/empty, prompt contains an
    'no source pages' placeholder rather than crashing."""
    from src.wiki.storage.ensure import ensure_knowledge_base
    from src.wiki.core.paths import WikiPaths
    from src.pipeline.generator import generate

    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)

    analysis = AnalysisResult(
        task_id="kb-1", source_path="raw/sources/x.md", summary="S",
        suggested_pages=[PageSpec(type="source", slug="kb-1", title="T", reasoning="r")],
    )
    provider = ScriptedLLMProvider([{"pages": []}])
    await generate(
        paths=paths, analysis=analysis, existing_wiki_index="",
        provider=provider, source_slug_map=None,
    )
    prompt = provider.calls[0]["messages"][0]["content"]
    assert "no source pages produced by this run" in prompt


# ---------------------------------------------------------------------------
# _auto_fill_deterministic_slots — main_content: LLM body preferred,
# denoised raw text only as fallback (empty / placeholder)
# ---------------------------------------------------------------------------


def test_auto_fill_preserves_llm_main_content():
    """LLM-organized main_content must NOT be overwritten by raw source text."""
    from src.pipeline.generator import _auto_fill_deterministic_slots
    organized = "LLM整理后的正文\n- 去噪\n- 保留列表"
    pages = [{"type": "source", "title": "测试", "slots": {"main_content": organized}}]
    _auto_fill_deterministic_slots(
        pages,
        source_path="raw/sources/测试.md",
        source_text="原始文本\n登录/注册\n评论（0）",
    )
    assert pages[0]["slots"]["main_content"] == organized


def test_auto_fill_drops_empty_main_content():
    """Empty main_content is NOT back-filled with the raw source — the full
    text lives in raw/ (RAG: source pages carry summary+metadata, not a
    duplicate full body). The slot is dropped so the optional 正文内容 section
    is omitted from the rendered body."""
    from src.pipeline.generator import _auto_fill_deterministic_slots
    pages = [{"type": "source", "title": "测试", "slots": {}}]
    _auto_fill_deterministic_slots(
        pages,
        source_path="raw/sources/测试.md",
        source_text="正文开始\n登录/注册\n评论（0）\n正文结束",
    )
    assert "main_content" not in pages[0]["slots"]


def test_auto_fill_drops_placeholder_main_content():
    """A placeholder in the optional main_content slot is cleared (dropped),
    not replaced with the raw source — no placeholder and no duplicate full
    text lands in the body."""
    from src.pipeline.generator import _auto_fill_deterministic_slots
    pages = [{
        "type": "source", "title": "测试",
        "slots": {"main_content": "（系统占位：此项由系统补齐，请人工补充）"},
    }]
    _auto_fill_deterministic_slots(
        pages,
        source_path="raw/sources/测试.md",
        source_text="真实内容\n正文",
    )
    assert "main_content" not in pages[0]["slots"]


# ---------------------------------------------------------------------------
# 0.5.2 — generated-id sanitisation (bad ids: tag-like / path-like /
# type-prefix / `-entity`)
# ---------------------------------------------------------------------------

def test_sanitize_keeps_clean_id():
    from src.pipeline.generator import _sanitize_generated_id
    assert _sanitize_generated_id("tolkien") == "tolkien"
    assert _sanitize_generated_id("穿越小说角色塑造套路") == "穿越小说角色塑造套路"
    assert _sanitize_generated_id("expectation-悬念") == "expectation-悬念"


def test_sanitize_strips_type_prefix():
    from src.pipeline.generator import _sanitize_generated_id
    assert _sanitize_generated_id("source-补充教程小说写作大纲的模版共享-a56031f5") == "补充教程小说写作大纲的模版共享-a56031f5"
    assert _sanitize_generated_id("concept-穿越小说角色塑造套路") == "穿越小说角色塑造套路"


def test_sanitize_strips_entity_suffix():
    from src.pipeline.generator import _sanitize_generated_id
    assert _sanitize_generated_id("琴帝-entity") == "琴帝"


def test_sanitize_repairs_tag_prefix():
    from src.pipeline.generator import _sanitize_generated_id
    assert _sanitize_generated_id("func-教程") == "教程"
    assert _sanitize_generated_id("题材-玄幻") == "玄幻"


def test_sanitize_drops_path_like():
    from src.pipeline.generator import _sanitize_generated_id
    assert _sanitize_generated_id("raw-sources-01-新手入门--入门教程三十六种经典情节模式情节艺术-md-9163987c") is None
    # `--` alone is now normalized to `-` (id-charset normalization runs
    # first), preserving the page with a compliant id instead of dropping it.
    assert _sanitize_generated_id("女频男频--架空类小说恶俗桥段盘点-8a5397b6") == "女频男频-架空类小说恶俗桥段盘点-8a5397b6"


def test_sanitize_normalizes_fullwidth_parens():
    """batch-50 H4 regression: full-width parens in LLM ids must be repaired."""
    from src.pipeline.generator import _sanitize_generated_id
    assert _sanitize_generated_id("元素化-（-写作问题-）") == "元素化-写作问题"
    assert _sanitize_generated_id("泰坦-（-普罗米修斯") == "泰坦-普罗米修斯"


def test_sanitize_normalizes_underscore():
    """Underscore in a generated id becomes '-' (id charset has no '_')."""
    from src.pipeline.generator import _sanitize_generated_id
    assert _sanitize_generated_id("大纲示例新人写大纲_7c8873") == "大纲示例新人写大纲-7c8873"


def test_is_bad_id_slug_detects_pollution_forms():
    from src.pipeline.generator import _is_bad_id_slug
    assert _is_bad_id_slug("func-教程")
    assert _is_bad_id_slug("题材-玄幻")
    assert _is_bad_id_slug("source-补充教程")
    assert _is_bad_id_slug("琴帝-entity")
    assert _is_bad_id_slug("raw-sources-01-新手入门")
    assert not _is_bad_id_slug("tolkien")
    assert not _is_bad_id_slug("修真")
    assert not _is_bad_id_slug("期望式悬念与突发式悬念")


@pytest.mark.asyncio
async def test_generate_sanitizes_bad_ids(tmp_path):
    """0.5.2 wiring: a type-prefix title is repaired to its bare id; a
    path-like title is dropped entirely. Source pages keep their
    deterministic slug and are unaffected."""
    from src.wiki.storage.ensure import ensure_knowledge_base
    from src.wiki.core.paths import WikiPaths
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)

    analysis = AnalysisResult(
        task_id="kb-1", source_path="raw/sources/x.pdf", summary="S",
        suggested_pages=[
            PageSpec(type="source", slug="kb-1", title="Article", reasoning="r"),
            PageSpec(type="concept", slug="t", title="source-补充教程", reasoning="r"),
            PageSpec(type="concept", slug="p", title="raw-sources-01-新手入门", reasoning="r"),
        ],
    )
    provider = ScriptedLLMProvider([{
        "pages": [
            {"id": "kb-1", "type": "source", "title": "Article",
             "slots": {"source_meta": "sm", "summary": "B",
                       "key_points": ["B"], "extracted_concepts": ["B"]}},
            {"id": "t", "type": "concept", "title": "source-补充教程",
             "slots": _concept_slots()},
            {"id": "p", "type": "concept", "title": "raw-sources-01-新手入门",
             "slots": _concept_slots()},
        ]
    }])
    pages = await generate(
        paths=paths, analysis=analysis, existing_wiki_index="", provider=provider,
    )
    ids = {p.id for p in pages}
    assert "article" in ids                     # source page survives
    assert "补充教程" in ids                      # type-prefix repaired
    assert not any("raw-sources" in i for i in ids)  # path-like dropped


# ---------------------------------------------------------------------------
# _resolve_page_tags / _resolve_page_tags_unified — tag namespace compliance
# ---------------------------------------------------------------------------
# Regression for the compile-flow blocker: the gate at write_page runs
# validate_tag_compliance (value domain + mandatory pairs), but the tag
# resolvers only dropped prefix-invalid tags, so value-invalid tags like
# `题材/穿越` and missing mandatory pairs (`素材/ugc`, `可信度/ugc`) escaped
# and every tagged page was rejected at commit. The resolvers must guarantee
# the documented invariant: the result always passes validate_tag_compliance.


def test_resolve_tags_unified_drops_value_invalid_keeps_valid():
    from src.pipeline.generator import _resolve_page_tags_unified
    tags = _resolve_page_tags_unified(
        {"tags": ["题材/穿越", "题材/玄幻", "素材/ugc", "可信度/ugc"]}
    )
    assert "题材/穿越" not in tags   # 穿越 not in the 题材 value domain
    assert "题材/玄幻" in tags
    assert "素材/ugc" in tags
    assert "可信度/ugc" in tags


def test_resolve_tags_unified_appends_mandatory_pairs():
    from src.pipeline.generator import _resolve_page_tags_unified
    tags = _resolve_page_tags_unified({"tags": ["题材/玄幻"]})
    assert "素材/ugc" in tags
    assert "可信度/ugc" in tags


def test_resolve_tags_unified_empty_and_all_invalid_stay_empty():
    from src.pipeline.generator import _resolve_page_tags_unified
    assert _resolve_page_tags_unified({"tags": []}) == []
    # No valid tag survives -> empty -> compliance skips mandatory check.
    assert _resolve_page_tags_unified({"tags": ["随意文本", "题材/穿越"]}) == []


def test_resolve_tags_result_always_passes_compliance():
    from src.pipeline.generator import _resolve_page_tags, _resolve_page_tags_unified
    from src.wiki.features.tag_namespace import validate_tag_compliance

    cases = [
        ({"tags": ["题材/穿越"]}, {}),                        # value-invalid only
        ({"tags": ["素材/ugc", "功能/教程", "状态/完结"]}, {}),  # valid but partial
        ({"tags": []}, {}),                                   # empty
        ({}, {"slug": ["情绪/爽文", "角色/总裁"]}),             # analyzer fallback
        ({"tags": "情绪/爽文"}, {}),                           # string form
    ]
    for page, analyzer_tags in cases:
        tags = _resolve_page_tags(page, "slug", analyzer_tags)
        validate_tag_compliance(tags)  # must not raise

    for page, _ in cases:
        tags = _resolve_page_tags_unified(page)
        validate_tag_compliance(tags)  # must not raise


def test_resolve_tags_uses_analyzer_fallback():
    from src.pipeline.generator import _resolve_page_tags
    tags = _resolve_page_tags({}, "s", {"s": ["情绪/爽文"]})
    assert "情绪/爽文" in tags
    assert "素材/ugc" in tags
    assert "可信度/ugc" in tags


# ---------------------------------------------------------------------------
# _call_with_slot_retry — max_tokens passthrough + truncation escalation
# ---------------------------------------------------------------------------
# Regression for the batch-10 observation: no max_tokens was sent, long
# multi-page JSON responses got truncated by the endpoint's default cap,
# and the retry loop wasted attempts on the misleading "JSON parse failed"
# path instead of escalating max_tokens.


def _make_tracking_provider(responses):
    """Fake provider recording (max_tokens, response) per call."""
    from src.llm.base import LLMResponse

    class _Fake:
        def __init__(self):
            self.calls: list[dict] = []

        async def complete(self, messages, *, response_format=None,
                           system=None, timeout=None, **kwargs):
            self.calls.append({
                "max_tokens": kwargs.get("max_tokens"),
                "messages": messages,
                "response": responses[len(self.calls)],
            })
            resp = responses[len(self.calls) - 1]
            if isinstance(resp, Exception):
                raise resp
            return resp

    return _Fake()


async def test_call_with_slot_retry_escalates_max_tokens_on_truncation():
    from src.llm.base import LLMResponse
    from src.pipeline.generator import _call_with_slot_retry

    valid = LLMResponse(
        content='{"pages": [{"id": "s", "type": "source", "title": "t"}]}',
        model="glm-5.2", truncated=False,
    )
    truncated = LLMResponse(
        content='{"pages": [{"id": "s", "type": "source", "title": "未完成',
        model="glm-5.2", truncated=True,
    )
    provider = _make_tracking_provider([truncated, valid])
    result = await _call_with_slot_retry(
        provider=provider,
        base_prompt="extract",
        response_format={},
        required_slots_by_type={},
        max_tokens=8192,
    )
    assert provider.calls[0]["max_tokens"] == 8192
    assert provider.calls[1]["max_tokens"] == 16384  # escalated after truncation
    assert result["pages"][0]["id"] == "s"


async def test_call_with_slot_retry_raises_clear_error_after_all_truncated():
    from src.llm.base import LLMResponse
    from src.pipeline.generator import _call_with_slot_retry

    truncated = LLMResponse(
        content='{"pages": [{"id": "s", "title": "未完成',
        model="glm-5.2", truncated=True,
    )
    provider = _make_tracking_provider([truncated, truncated, truncated])
    with pytest.raises(RuntimeError, match="truncat"):
        await _call_with_slot_retry(
            provider=provider,
            base_prompt="extract",
            response_format={},
            required_slots_by_type={},
            max_tokens=8192,
        )
    assert [c["max_tokens"] for c in provider.calls] == [8192, 16384, 32768]


async def test_call_with_slot_retry_passes_max_tokens_forwards():
    from src.llm.base import LLMResponse
    from src.pipeline.generator import _call_with_slot_retry

    ok = LLMResponse(
        content='{"pages": [{"id": "s", "type": "source", "title": "t"}]}',
        model="glm-5.2", truncated=False,
    )
    provider = _make_tracking_provider([ok])
    await _call_with_slot_retry(
        provider=provider,
        base_prompt="extract",
        response_format={},
        required_slots_by_type={},
        max_tokens=4096,
    )
    assert provider.calls[0]["max_tokens"] == 4096


async def test_call_with_slot_retry_no_escalation_on_empty_truncation():
    """finish_reason=length with 0 content chars (sfkey quirk) must NOT
    escalate max_tokens — escalating is useless when nothing was generated.
    Regression from batch-50: ~10 wasted escalation retries on '0 chars'."""
    from src.llm.base import LLMResponse
    from src.pipeline.generator import _call_with_slot_retry

    empty_truncated = LLMResponse(
        content="", model="glm-5.2", truncated=True,
    )
    valid = LLMResponse(
        content='{"pages": [{"id": "s", "type": "source", "title": "t"}]}',
        model="glm-5.2", truncated=False,
    )
    provider = _make_tracking_provider([empty_truncated, valid])
    result = await _call_with_slot_retry(
        provider=provider,
        base_prompt="extract",
        response_format={},
        required_slots_by_type={},
        max_tokens=8192,
    )
    # No escalation: both attempts use the base max_tokens.
    assert provider.calls[0]["max_tokens"] == 8192
    assert provider.calls[1]["max_tokens"] == 8192
    assert result["pages"][0]["id"] == "s"


async def test_call_with_slot_retry_escalation_still_applies_after_empty():
    """An empty truncation followed by a content truncation still escalates."""
    from src.llm.base import LLMResponse
    from src.pipeline.generator import _call_with_slot_retry

    empty_truncated = LLMResponse(content="", model="glm-5.2", truncated=True)
    content_truncated = LLMResponse(
        content='{"pages": [{"id": "s", "title": "未完成',
        model="glm-5.2", truncated=True,
    )
    valid = LLMResponse(
        content='{"pages": [{"id": "s", "type": "source", "title": "t"}]}',
        model="glm-5.2", truncated=False,
    )
    provider = _make_tracking_provider([empty_truncated, content_truncated, valid])
    await _call_with_slot_retry(
        provider=provider,
        base_prompt="extract",
        response_format={},
        required_slots_by_type={},
        max_tokens=8192,
    )
    assert provider.calls[0]["max_tokens"] == 8192   # attempt 0: base
    assert provider.calls[1]["max_tokens"] == 8192   # empty truncation: no escalation
    assert provider.calls[2]["max_tokens"] == 16384  # content truncation: escalated


async def test_call_with_slot_retry_no_escalation_on_repeated_empty_truncation():
    """连续 2 次纯空截断（无 reasoning_content）仍不升级——thinking 场景
    已在 provider 层（openai_provider.py）通过 content_length 走正常升级
    路径，纯空截断没有内容可生成，升级无用。"""
    from src.llm.base import LLMResponse
    from src.pipeline.generator import _call_with_slot_retry

    empty_truncated = LLMResponse(
        content="", model="glm-5.2", truncated=True,
    )
    valid = LLMResponse(
        content='{"pages": [{"id": "s", "type": "source", "title": "t"}]}',
        model="glm-5.2", truncated=False,
    )
    provider = _make_tracking_provider([empty_truncated, empty_truncated, valid])
    result = await _call_with_slot_retry(
        provider=provider,
        base_prompt="extract",
        response_format={},
        required_slots_by_type={},
        max_tokens=8192,
    )
    # 纯空截断不升级，所有尝试都用 base max_tokens
    for c in provider.calls:
        assert c["max_tokens"] == 8192
    assert result["pages"][0]["id"] == "s"


# ---------------------------------------------------------------------------
# 1.3 H6 — missing_slugs_resolver：单调用内闭环（引用-产出对账反馈）
# ---------------------------------------------------------------------------

async def test_call_with_slot_retry_escalates_when_reasoning_consumed_budget():
    """Phase 4 缺陷 F 端到端：provider 对 thinking 占满预算的响应上报
    content_length>0 → _call_with_slot_retry 视为非空截断 → 升级 max_tokens。
    模拟真实 sfkey 返回（reasoning_content 非空、content 空、length）。
    注：这里直接构造 provider 返回 TruncatedResponseError(content_length>0)
    等价于 provider 层已正确上报，验证升级链路。"""
    from src.llm.types import TruncatedResponseError
    from src.pipeline.generator import _call_with_slot_retry

    class _ReasoningProvider:
        """Fake provider: first call returns LLMResponse with truncated=True
        and content_length=4000 (thinking 占满预算等效), second returns valid."""
        calls: list[dict] = []

        async def complete(self, messages, **kwargs):
            self.calls.append({"max_tokens": kwargs.get("max_tokens")})
            if len(self.calls) == 1:
                from src.llm.base import LLMResponse
                return LLMResponse(
                    content="", model="glm-5.2", truncated=True,
                    content_length=4000,
                )
            return type(
                "R", (), {
                    "content": '{"pages": [{"id": "s", "type": "source", "title": "t"}]}',
                    "truncated": False, "content_length": 0,
                })()

    provider = _ReasoningProvider()
    result = await _call_with_slot_retry(
        provider=provider,
        base_prompt="extract",
        response_format={},
        required_slots_by_type={},
        max_tokens=8192,
    )
    assert provider.calls[0]["max_tokens"] == 8192
    assert provider.calls[1]["max_tokens"] == 16384  # thinking 截断 → 升级
    assert result["pages"][0]["id"] == "s"

async def test_call_with_slot_retry_feeds_missing_slugs_back():
    """首次产出引用幽灵 slug → resolver 报缺失 → 反馈进 prompt → 二次产出修正。"""
    from src.llm.base import LLMResponse
    from src.pipeline.generator import _call_with_slot_retry

    ghost = LLMResponse(
        content='{"pages": [{"id": "a", "type": "concept", "title": "A",'
                ' "relations": [{"target": "幽灵概念"}]}]}',
        model="glm-5.2", truncated=False,
    )
    fixed = LLMResponse(
        content='{"pages": [{"id": "a", "type": "concept", "title": "A",'
                ' "relations": [{"target": "现实概念"}]}]}',
        model="glm-5.2", truncated=False,
    )
    provider = _make_tracking_provider([ghost, fixed])

    seen = []

    def resolver(pages):
        targets = [r.get("target") for p in pages
                   for r in (p.get("relations") or []) if r.get("target")]
        missing = [t for t in targets if t not in {"现实概念", "a"}]
        seen.append(list(missing))
        return missing

    result = await _call_with_slot_retry(
        provider=provider,
        base_prompt="extract",
        response_format={},
        required_slots_by_type={},
        max_tokens=8192,
        missing_slugs_resolver=resolver,
    )
    assert len(provider.calls) == 2
    assert seen == [["幽灵概念"], []]  # 首轮报缺失，二轮已修正
    # 二轮 prompt 必须包含缺失 slug 反馈（单调用内闭环的证据）
    second_prompt = provider.calls[1]["messages"][0]["content"]
    assert "幽灵概念" in second_prompt
    assert "MISSING PAGES" in second_prompt
    assert result["pages"][0]["relations"][0]["target"] == "现实概念"


async def test_call_with_slot_retry_missing_slugs_exhausted_returns_last():
    """重试预算耗尽后仍返回本次产出（缺失由调用方记 gap，不抛错）。"""
    from src.llm.base import LLMResponse
    from src.pipeline.generator import _call_with_slot_retry

    always_ghost = LLMResponse(
        content='{"pages": [{"id": "a", "type": "concept", "title": "A",'
                ' "relations": [{"target": "幽灵概念"}]}]}',
        model="glm-5.2", truncated=False,
    )
    provider = _make_tracking_provider([always_ghost, always_ghost, always_ghost])

    def resolver(pages):
        return ["幽灵概念"]

    result = await _call_with_slot_retry(
        provider=provider,
        base_prompt="extract",
        response_format={},
        required_slots_by_type={},
        max_tokens=8192,
        missing_slugs_resolver=resolver,
    )
    assert len(provider.calls) == 3  # 初始 + 2 次反馈重试
    assert result["pages"][0]["relations"][0]["target"] == "幽灵概念"


async def test_call_with_slot_retry_no_resolver_unaffected():
    """未传 resolver 时行为与既有实现一致（单次调用返回）。"""
    from src.llm.base import LLMResponse
    from src.pipeline.generator import _call_with_slot_retry

    ok = LLMResponse(
        content='{"pages": [{"id": "s", "type": "source", "title": "t"}]}',
        model="glm-5.2", truncated=False,
    )
    provider = _make_tracking_provider([ok])
    result = await _call_with_slot_retry(
        provider=provider,
        base_prompt="extract",
        response_format={},
        required_slots_by_type={},
        max_tokens=8192,
    )
    assert len(provider.calls) == 1
    assert result["pages"][0]["id"] == "s"
