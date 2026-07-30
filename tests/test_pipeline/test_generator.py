# tests/test_pipeline/test_generator.py
import pytest
from src.shared.test_helpers import ScriptedLLMProvider
from src.pipeline.schemas import AnalysisResult, EntityMention, PageSpec
from src.pipeline.generator import generate
from src.wiki.core.types import PageType, WikiPage


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
    assert pages[0].id == "kb-1"
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
    # Placeholder text should appear under each missing heading.
    assert "（系统占位" in body
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
