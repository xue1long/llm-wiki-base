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
             "body_markdown": "Article body"},
            {"id": "backprop", "type": "concept", "title": "Backprop",
             "frontmatter_extra": {"tags": []},
             "body_markdown": "Backprop body"},
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
             "body_markdown": "B",
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
             "body_markdown": "B"},
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
    the constructed WikiPage still gets the v2.2 defaults (B / concept / False).
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
            {"id": "kb-1", "type": "source", "title": "T", "body_markdown": "B"},
        ]}
    ])
    pages = await generate(paths=paths, analysis=analysis, existing_wiki_index="", provider=provider)
    assert len(pages) == 1
    assert pages[0].grade == "B"
    assert pages[0].processing_depth == "concept"
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
             "body_markdown": "B"},
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
             "body_markdown": "B"},
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
                    "body_markdown": "B"}]
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
                    "body_markdown": "B"}]
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
                    "body_markdown": "B"}]
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
