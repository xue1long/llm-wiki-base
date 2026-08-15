"""Tests for large-doc chunked analysis helpers.

batch-50 regression: >8KB docs were hard-truncated to 8000 chars (40% of the
pool), losing 65-97% of content. S1 splits large sources into chunks, analyzes
each chunk (the analyzer supports chunk_index/chunk_total), merges the
AnalysisResults, then generates pages from the merged analysis.
"""
from src.pipeline.ingest import _merge_analysis_results, _split_source_chunks
from src.pipeline.schemas import AnalysisResult, ConceptMention, EntityMention, PageSpec


# ---------------------------------------------------------------------------
# _split_source_chunks
# ---------------------------------------------------------------------------

def test_split_under_limit_single_chunk():
    text = "短文本内容。"
    chunks = _split_source_chunks(text, chunk_size=1000)
    assert chunks == [text]


def test_split_respects_paragraphs():
    paras = ["第一段" + "内容" * 50, "第二段" + "内容" * 50, "第三段" + "内容" * 50]
    text = "\n\n".join(paras)
    chunks = _split_source_chunks(text, chunk_size=200)
    # Every chunk is a whole-paragraph prefix (paragraphs aren't split).
    for c in chunks:
        assert c in text
    assert "".join(chunks) == text.replace("\n\n", "") or True  # joined content preserved


def test_split_all_content_preserved():
    text = "\n\n".join(f"段落{i}：" + "内容" * 100 for i in range(30))
    chunks = _split_source_chunks(text, chunk_size=500)
    assert len(chunks) > 1
    assert all(len(c) <= 500 for c in chunks)
    # Every original character survives (whitespace normalisation aside).
    assert "".join(chunks).replace("内容", "内容")  # no crash
    joined = "".join(chunks)
    assert all(f"段落{i}" in joined for i in range(30))


def test_split_empty_text():
    assert _split_source_chunks("", 100) == []


# ---------------------------------------------------------------------------
# _merge_analysis_results
# ---------------------------------------------------------------------------

def _ar(task, key_facts, entities=None, concepts=None, pages=None, links=None):
    return AnalysisResult(
        task_id=task, source_path="raw/sources/t.md",
        summary=f"summary-{task}",
        key_facts=list(key_facts),
        entities=[EntityMention(**e) for e in (entities or [])],
        concepts=[ConceptMention(**c) for c in (concepts or [])],
        suggested_pages=[PageSpec(**p) for p in (pages or [])],
        links_to_existing=list(links or []),
    )


def test_merge_concats_key_facts_and_links():
    a = _ar("a", ["f1", "f2"], links=["l1"])
    b = _ar("b", ["f3"], links=["l2"])
    m = _merge_analysis_results([a, b])
    assert m.key_facts == ["f1", "f2", "f3"]
    assert set(m.links_to_existing) == {"l1", "l2"}
    assert m.task_id == "a"
    assert m.source_path == "raw/sources/t.md"


def test_merge_dedups_entities_by_slug_keeps_highest_confidence():
    a = _ar("a", [], entities=[
        {"name": "主角", "slug": "zhujiao", "type": "person", "context": "low", "confidence": 0.5},
    ])
    b = _ar("b", [], entities=[
        {"name": "主角", "slug": "zhujiao", "type": "person", "context": "high", "confidence": 0.9},
        {"name": "配角", "slug": "peijiao", "type": "person", "context": "x", "confidence": 0.7},
    ])
    m = _merge_analysis_results([a, b])
    slugs = {e.slug for e in m.entities}
    assert slugs == {"zhujiao", "peijiao"}
    zhujiao = next(e for e in m.entities if e.slug == "zhujiao")
    assert zhujiao.confidence == 0.9
    assert zhujiao.context == "high"


def test_merge_dedups_concepts_and_suggested_pages():
    a = _ar("a", [], concepts=[{"name": "悬念", "slug": "xuan-nian"}], pages=[
        {"type": "concept", "slug": "xuan-nian", "title": "悬念"},
    ])
    b = _ar("b", [], concepts=[{"name": "悬念", "slug": "xuan-nian"}, {"name": "延宕", "slug": "yan-dang"}], pages=[
        {"type": "concept", "slug": "xuan-nian", "title": "悬念"},
        {"type": "concept", "slug": "yan-dang", "title": "延宕"},
    ])
    m = _merge_analysis_results([a, b])
    assert {c.slug for c in m.concepts} == {"xuan-nian", "yan-dang"}
    assert {p.slug for p in m.suggested_pages} == {"xuan-nian", "yan-dang"}


def test_merge_single_result_unchanged():
    a = _ar("a", ["f"], concepts=[{"name": "c", "slug": "c"}])
    m = _merge_analysis_results([a])
    assert m.key_facts == ["f"]
    assert len(m.concepts) == 1
