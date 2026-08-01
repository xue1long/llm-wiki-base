"""NDG Phase 3: tests for P1–P7 + P4b gate checks.

Each test constructs synthetic pages and asserts that the specific
violation code is (or is not) produced.
"""
import pytest
from pathlib import Path

from src.wiki.core.types import PageType, WikiPage
from src.wiki.core.paths import WikiPaths
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.features.relations import Relation
from src.wiki.features.ndg_gate import (
    check_page,
    check_batch,
    run_ndg_gate,
    is_ugc_source,
    GateIssue,
    GateReport,
)


# ---------------------------------------------------------------------------
# P1 — READABILITY
# ---------------------------------------------------------------------------

def test_p1_empty_id():
    page = WikiPage(id="", title="T", type=PageType.ENTITY, body="x")
    issues = check_page(page)
    assert any(i.code == "P1" for i in issues)

def test_p1_empty_title():
    page = WikiPage(id="x", title="", type=PageType.ENTITY, body="x")
    issues = check_page(page)
    assert any(i.code == "P1" for i in issues)

def test_p1_empty_body():
    page = WikiPage(id="x", title="T", type=PageType.ENTITY, body="")
    issues = check_page(page)
    assert any(i.code == "P1" for i in issues)

def test_p1_placeholder_body():
    for placeholder in ("(empty)", "(无内容)", "(占位)", "(placeholder)"):
        page = WikiPage(id="x", title="T", type=PageType.ENTITY, body=placeholder)
        issues = check_page(page)
        assert any(i.code == "P1" for i in issues), f"placeholder {placeholder!r}"

def test_p1_clean():
    page = WikiPage(id="x", title="T", type=PageType.ENTITY, body="Some content.")
    issues = check_page(page)
    assert not any(i.code == "P1" for i in issues)


# ---------------------------------------------------------------------------
# P2 — RAW-PASTE
# ---------------------------------------------------------------------------

def test_p2_source_fulltext_heading():
    """Source page with ## 正文内容 → P2."""
    page = WikiPage(id="s", title="S", type=PageType.SOURCE,
                     body="## 正文内容\n\nfull text here", sources=["a.md"])
    issues = check_page(page)
    assert any(i.code == "P2" for i in issues)

def test_p2_source_transcript_heading():
    """Source page with ## 转录内容 → P2."""
    page = WikiPage(id="s", title="S", type=PageType.SOURCE,
                     body="## 转录内容\n\ntranscript", sources=["a.md"])
    issues = check_page(page)
    assert any(i.code == "P2" for i in issues)

def test_p2_source_short_distilled():
    """Source page with short summary → clean."""
    page = WikiPage(id="s", title="S", type=PageType.SOURCE,
                     body="## 摘要\n\nShort summary.", sources=["a.md"])
    issues = check_page(page)
    assert not any(i.code == "P2" for i in issues)

def test_p2_source_long_raw_run():
    """Source page with >T_source raw run → P2."""
    long_text = "\n".join("line {} with a lot of plain text that just keeps going".format(i) for i in range(60))
    assert len(long_text) > 2000
    page = WikiPage(id="s", title="S", type=PageType.SOURCE,
                     body=long_text, sources=["a.md"])
    issues = check_page(page, T_source=2000)
    assert any(i.code == "P2" for i in issues)

def test_p2_non_source_long_run():
    """Concept page with >T_non raw run → P2."""
    long_text = "\n".join("line {} of raw unformatted prose text".format(i) for i in range(15))
    assert len(long_text) > 300
    page = WikiPage(id="c", title="C", type=PageType.CONCEPT,
                     body=long_text, sources=["a.md"])
    issues = check_page(page, T_non=300)
    assert any(i.code == "P2" for i in issues)

def test_p2_non_source_short_run():
    """Concept page with short run → clean."""
    page = WikiPage(id="c", title="C", type=PageType.CONCEPT,
                     body="## 定义\n\nShort definition.", sources=["a.md"])
    issues = check_page(page)
    assert not any(i.code == "P2" for i in issues)


# ---------------------------------------------------------------------------
# P3 — MISSING-SOURCES
# ---------------------------------------------------------------------------

def test_p3_missing_sources_no_relation():
    page = WikiPage(id="x", title="X", type=PageType.CONCEPT, body="content")
    issues = check_page(page)
    assert any(i.code == "P3" for i in issues)

def test_p3_has_sources():
    page = WikiPage(id="x", title="X", type=PageType.CONCEPT, body="c",
                     sources=["raw/a.md"])
    issues = check_page(page)
    assert not any(i.code == "P3" for i in issues)

def test_p3_has_derived_from():
    page = WikiPage(id="x", title="X", type=PageType.CONCEPT, body="c",
                     relations=[Relation(target_id="src-a", type="derived_from")])
    issues = check_page(page)
    assert not any(i.code == "P3" for i in issues)


# ---------------------------------------------------------------------------
# P4 — UGC-CRED
# ---------------------------------------------------------------------------

def test_p4_ugc_without_cred():
    page = WikiPage(id="u", title="U", type=PageType.CONCEPT, body="c",
                     tags=["素材/ugc"], sources=["a.md"])
    issues = check_page(page)
    assert any(i.code == "P4" for i in issues)

def test_p4_ugc_with_cred():
    page = WikiPage(id="u", title="U", type=PageType.CONCEPT, body="c",
                     tags=["素材/ugc", "可信度/ugc"], sources=["a.md"])
    issues = check_page(page)
    assert not any(i.code == "P4" for i in issues)

def test_p4_no_ugc_tags():
    page = WikiPage(id="u", title="U", type=PageType.CONCEPT, body="c",
                     tags=["题材/玄幻"], sources=["a.md"])
    issues = check_page(page)
    assert not any(i.code == "P4" for i in issues)


# ---------------------------------------------------------------------------
# P4b — UGC-SOURCE-TAG (raw-level enforcement)
# ---------------------------------------------------------------------------

def test_p4b_ugc_source_missing_tags():
    """is_ugc_source=True but page lacks UGC tags → P4b."""
    page = WikiPage(id="u", title="U", type=PageType.CONCEPT, body="c",
                     sources=["raw/a.md"])
    issues = check_page(page, is_ugc_source=True)
    assert any(i.code == "P4b" for i in issues)

def test_p4b_ugc_source_has_tags():
    """is_ugc_source=True and page has both tags → clean."""
    page = WikiPage(id="u", title="U", type=PageType.CONCEPT, body="c",
                     tags=["素材/ugc", "可信度/ugc"], sources=["raw/a.md"])
    issues = check_page(page, is_ugc_source=True)
    assert not any(i.code == "P4b" for i in issues)

def test_p4b_not_ugc_source():
    """is_ugc_source=False → P4b is skipped."""
    page = WikiPage(id="u", title="U", type=PageType.CONCEPT, body="c",
                     sources=["raw/a.md"])
    issues = check_page(page, is_ugc_source=False)
    assert not any(i.code == "P4b" for i in issues)


# ---------------------------------------------------------------------------
# is_ugc_source — header detection
# ---------------------------------------------------------------------------

def test_is_ugc_source_detects_markers():
    assert is_ugc_source("本文来自 feishu.cn 文档")
    assert is_ugc_source("mp.weixin.qq.com 公众号文章")
    assert is_ugc_source("来源：知乎专栏")
    assert is_ugc_source("豆瓣小组讨论")

def test_is_ugc_source_clean_text():
    assert not is_ugc_source("这是一本正式出版的书籍内容")
    assert not is_ugc_source("学术论文摘要")
    assert not is_ugc_source("")


# ---------------------------------------------------------------------------
# P5 — INPUT-SOURCE-PAIR
# ---------------------------------------------------------------------------

def test_p5_missing_source_page():
    """Raw file with no SOURCE page → P5."""
    pages = [WikiPage(id="e", title="E", type=PageType.ENTITY,
                       body="c", sources=["raw/a.txt"])]
    raw_headers = {"raw/a.txt": "some content"}
    issues = check_batch(pages, raw_headers=raw_headers)
    assert any(i.code == "P5" for i in issues)

def test_p5_has_source_page():
    """Raw file with matching SOURCE page → clean."""
    pages = [
        WikiPage(id="s", title="S", type=PageType.SOURCE,
                  body="summary", sources=["raw/a.txt"]),
        WikiPage(id="e", title="E", type=PageType.ENTITY,
                  body="c", sources=["raw/a.txt"]),
    ]
    raw_headers = {"raw/a.txt": "some content"}
    issues = check_batch(pages, raw_headers=raw_headers)
    assert not any(i.code == "P5" for i in issues)


# ---------------------------------------------------------------------------
# P6 — SLUG-CONFLICT
# ---------------------------------------------------------------------------

def test_p6_slug_cross_type_conflict():
    """Same slug, different types → P6."""
    pages = [
        WikiPage(id="dup", title="D", type=PageType.ENTITY, body="a"),
        WikiPage(id="dup", title="D", type=PageType.CONCEPT, body="b"),
    ]
    issues = check_batch(pages)
    assert any(i.code == "P6" for i in issues)

def test_p6_slug_same_type_ok():
    """Same slug, same type (overwrite) → clean."""
    pages = [
        WikiPage(id="dup", title="D1", type=PageType.ENTITY, body="a"),
        WikiPage(id="dup", title="D2", type=PageType.ENTITY, body="b"),
    ]
    issues = check_batch(pages)
    assert not any(i.code == "P6" for i in issues)

def test_p6_unique_slugs():
    pages = [
        WikiPage(id="a", title="A", type=PageType.ENTITY, body="x"),
        WikiPage(id="b", title="B", type=PageType.CONCEPT, body="y"),
    ]
    issues = check_batch(pages)
    assert not any(i.code == "P6" for i in issues)


# ---------------------------------------------------------------------------
# P7 — EXTRA-PAGES overwrite guard
# ---------------------------------------------------------------------------

def test_p7_extra_page_would_overwrite_non_stub(tmp_path: Path):
    """Extra page whose slug already exists as non-stub on disk → P7."""
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)

    # Write a real non-stub page to disk first.
    from src.wiki.storage.page_writer import write_page
    existing = WikiPage(id="exist", title="Exist", type=PageType.ENTITY,
                         body="existing", processing_depth="concept")
    write_page(paths, existing)

    extra = [WikiPage(id="exist", title="Exist2", type=PageType.ENTITY,
                       body="new", processing_depth="concept")]
    issues = check_batch([], extra_pages=extra, paths=paths)
    assert any(i.code == "P7" for i in issues)

def test_p7_extra_page_overwrite_stub_ok(tmp_path: Path):
    """Extra page overwriting a stub → clean (stub upgrade is by design)."""
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)

    from src.wiki.storage.page_writer import write_page
    stub = WikiPage(id="stub-x", title="Stub", type=PageType.ENTITY,
                     body="stub body", processing_depth="stub")
    write_page(paths, stub)

    extra = [WikiPage(id="stub-x", title="Real", type=PageType.ENTITY,
                       body="real content", processing_depth="concept")]
    issues = check_batch([], extra_pages=extra, paths=paths)
    assert not any(i.code == "P7" for i in issues), (
        f"stub→real upgrade must be allowed, got: {issues}"
    )

def test_p7_no_extra_pages():
    issues = check_batch([], extra_pages=None)
    assert not any(i.code == "P7" for i in issues)


# ---------------------------------------------------------------------------
# run_ndg_gate — integration
# ---------------------------------------------------------------------------

def test_run_ndg_gate_all_clean():
    """A batch with valid pages → PASS."""
    pages = [
        WikiPage(id="s-abc12345", title="Source", type=PageType.SOURCE,
                  body="## 摘要\n\nShort summary.", sources=["raw/a.txt"]),
        WikiPage(id="ent-1", title="Entity", type=PageType.ENTITY,
                  body="## 基本信息\n\nInfo.", sources=["raw/a.txt"]),
    ]
    report = run_ndg_gate(pages)
    assert report.passed
    assert report.blocker_count == 0

def test_run_ndg_gate_with_violations():
    """A batch with issues → FAIL."""
    pages = [
        WikiPage(id="bad", title="", type=PageType.ENTITY,
                  body="", sources=[]),
    ]
    report = run_ndg_gate(pages)
    assert not report.passed
    assert report.blocker_count > 0
    codes = {i.code for i in report.issues}
    assert "P1" in codes  # empty title + empty body
    assert "P3" in codes  # no sources

def test_run_ndg_gate_ugc_batch():
    """UGC raw file with derived pages lacking tags → P4b fires."""
    pages = [
        WikiPage(id="s-hash1234", title="Source", type=PageType.SOURCE,
                  body="## 摘要\n\nok", sources=["raw/ugc.txt"]),
        WikiPage(id="ent-1", title="Entity", type=PageType.ENTITY,
                  body="content", sources=["raw/ugc.txt"]),
    ]
    raw_headers = {"raw/ugc.txt": "mp.weixin.qq.com 公众号文章内容"}
    report = run_ndg_gate(pages, raw_headers=raw_headers)
    # entity page should get P4b since the raw is UGC and page lacks tags
    p4b_issues = [i for i in report.issues if i.code == "P4b"]
    assert len(p4b_issues) >= 1
    assert not report.passed
