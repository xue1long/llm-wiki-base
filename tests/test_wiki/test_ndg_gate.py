"""NDG Phase 3: tests for P1–P7 gate checks.

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
    page = WikiPage(id="s", title="S", type=PageType.SOURCE,
                     body="## 正文内容\n\nfull text here", sources=["a.md"])
    issues = check_page(page)
    assert any(i.code == "P2" for i in issues)

def test_p2_source_transcript_heading():
    page = WikiPage(id="s", title="S", type=PageType.SOURCE,
                     body="## 转录内容\n\ntranscript", sources=["a.md"])
    issues = check_page(page)
    assert any(i.code == "P2" for i in issues)

def test_p2_source_short_distilled():
    page = WikiPage(id="s", title="S", type=PageType.SOURCE,
                     body="## 摘要\n\nShort summary.", sources=["a.md"])
    issues = check_page(page)
    assert not any(i.code == "P2" for i in issues)

def test_p2_source_long_raw_run():
    long_text = "\n".join("line {} with a lot of plain text that just keeps going".format(i) for i in range(60))
    assert len(long_text) > 2000
    page = WikiPage(id="s", title="S", type=PageType.SOURCE,
                     body=long_text, sources=["a.md"])
    issues = check_page(page, T_source=2000)
    assert any(i.code == "P2" for i in issues)

def test_p2_non_source_long_run():
    long_text = "\n".join("line {} of raw unformatted prose text".format(i) for i in range(15))
    assert len(long_text) > 300
    page = WikiPage(id="c", title="C", type=PageType.CONCEPT,
                     body=long_text, sources=["a.md"])
    issues = check_page(page, T_non=300)
    assert any(i.code == "P2" for i in issues)

def test_p2_non_source_short_run():
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
# P5 — INPUT-SOURCE-PAIR (warning only)
# ---------------------------------------------------------------------------

def test_p5_missing_source_page():
    """Raw file with no SOURCE page → P5 warning (not blocker)."""
    pages = [WikiPage(id="e", title="E", type=PageType.ENTITY,
                       body="c", sources=["raw/a.txt"])]
    raw_headers = {"raw/a.txt": "some content"}
    issues = check_batch(pages, raw_headers=raw_headers)
    p5 = [i for i in issues if i.code == "P5"]
    assert len(p5) == 1
    assert p5[0].is_blocker is False, "P5 must be warning-only"

def test_p5_has_source_page():
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
    pages = [
        WikiPage(id="dup", title="D", type=PageType.ENTITY, body="a"),
        WikiPage(id="dup", title="D", type=PageType.CONCEPT, body="b"),
    ]
    issues = check_batch(pages)
    assert any(i.code == "P6" for i in issues)

def test_p6_slug_same_type_ok():
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
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)

    from src.wiki.storage.page_writer import write_page
    existing = WikiPage(id="exist", title="Exist", type=PageType.ENTITY,
                         body="existing", processing_depth="concept")
    write_page(paths, existing)

    extra = [WikiPage(id="exist", title="Exist2", type=PageType.ENTITY,
                       body="new", processing_depth="concept")]
    issues = check_batch([], extra_pages=extra, paths=paths)
    assert any(i.code == "P7" for i in issues)

def test_p7_extra_page_same_body_reverse_relation_ok(tmp_path: Path):
    """B13 reverse-edge update: extra body equals the disk body (only
    relations differ) → P7 stays silent."""
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)

    from src.wiki.storage.page_writer import write_page
    existing = WikiPage(id="ent-1", title="Entity", type=PageType.ENTITY,
                         body="## 基本信息\n\nInfo.", processing_depth="concept",
                         sources=["raw/a.txt"])
    write_page(paths, existing)

    extra = [WikiPage(id="ent-1", title="Entity", type=PageType.ENTITY,
                       body="## 基本信息\n\nInfo.", processing_depth="concept",
                       sources=["raw/a.txt"],
                       relations=[Relation(target_id="src-other",
                                           type="related_to")])]
    issues = check_batch([], extra_pages=extra, paths=paths)
    assert not any(i.code == "P7" for i in issues)

def test_p7_extra_page_different_body_allow_overwrite_warning(tmp_path: Path):
    """Destructive overwrite downgraded to warning under --allow-overwrite."""
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)

    from src.wiki.storage.page_writer import write_page
    existing = WikiPage(id="exist", title="Exist", type=PageType.ENTITY,
                         body="existing", processing_depth="concept")
    write_page(paths, existing)

    extra = [WikiPage(id="exist", title="Exist2", type=PageType.ENTITY,
                       body="new", processing_depth="concept")]
    issues = check_batch([], extra_pages=extra, paths=paths,
                         allow_overwrite=True)
    p7 = [i for i in issues if i.code == "P7"]
    assert len(p7) == 1
    assert not p7[0].is_blocker, "P7 must be warning-only under allow_overwrite"

def test_p7_extra_page_overwrite_stub_ok(tmp_path: Path):
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)

    from src.wiki.storage.page_writer import write_page
    stub = WikiPage(id="stub-x", title="Stub", type=PageType.ENTITY,
                     body="stub body", processing_depth="stub")
    write_page(paths, stub)

    extra = [WikiPage(id="stub-x", title="Real", type=PageType.ENTITY,
                       body="real content", processing_depth="concept")]
    issues = check_batch([], extra_pages=extra, paths=paths)
    assert not any(i.code == "P7" for i in issues)

def test_p7_no_extra_pages():
    issues = check_batch([], extra_pages=None)
    assert not any(i.code == "P7" for i in issues)


# ---------------------------------------------------------------------------
# run_ndg_gate — integration
# ---------------------------------------------------------------------------

def test_run_ndg_gate_all_clean():
    pages = [
        WikiPage(id="s-abc12345", title="Source", type=PageType.SOURCE,
                  body="## 摘要\n\nShort summary.", sources=["raw/a.txt"]),
        WikiPage(id="ent-1", title="Entity", type=PageType.ENTITY,
                  body="## 基本信息\n\nInfo.", sources=["raw/a.txt"]),
    ]
    report = run_ndg_gate(pages)
    assert report.passed
    assert report.blocker_count == 0

def test_run_ndg_gate_with_batch_violation():
    """run_ndg_gate blocks on a batch-level violation (P6 cross-type slug
    conflict) — the gate now only enforces P5/P6/P7."""
    pages = [
        WikiPage(id="dup", title="E", type=PageType.ENTITY,
                  body="content", sources=["raw/x.txt"]),
        WikiPage(id="dup", title="C", type=PageType.CONCEPT,
                  body="content", sources=["raw/x.txt"]),
    ]
    report = run_ndg_gate(pages)
    assert not report.passed
    assert report.blocker_count > 0
    codes = {i.code for i in report.issues}
    assert "P6" in codes


def test_run_ndg_gate_p1_p4_warnings_not_blockers():
    """P1–P4 issues are surfaced as warnings (is_blocker=False) so page
    quality is visible at write time, without changing block semantics."""
    pages = [
        WikiPage(id="", title="", type=PageType.ENTITY,
                  body="", sources=[]),
    ]
    report = run_ndg_gate(pages)
    codes = {i.code for i in report.issues}
    assert codes & {"P1", "P3"}, (
        f"expected P1-P4 warnings in report, got {sorted(codes)}"
    )
    p14 = [i for i in report.issues if i.code in {"P1", "P2", "P3", "P4"}]
    assert p14, "P1-P4 issues must be present in the report"
    assert all(not i.is_blocker for i in p14), "P1-P4 must be warnings"
    assert report.passed, "P1-P4 warnings must not block the batch"
    assert report.blocker_count == 0

def test_run_ndg_gate_empty_body_p1_warning():
    """Empty-body page → P1 warning in the report, batch still passes."""
    pages = [
        WikiPage(id="ent-1", title="Entity", type=PageType.ENTITY,
                  body="", sources=["raw/a.txt"]),
    ]
    report = run_ndg_gate(pages)
    p1 = [i for i in report.issues if i.code == "P1"]
    assert len(p1) == 1
    assert not p1[0].is_blocker
    assert report.passed
    assert report.blocker_count == 0

def test_run_ndg_gate_p5_is_warning_not_blocker():
    """P5 fires but doesn't block the batch."""
    pages = [
        WikiPage(id="ent-1", title="Entity", type=PageType.ENTITY,
                  body="content", sources=["raw/x.txt"]),
    ]
    raw_headers = {"raw/x.txt": "some content"}
    report = run_ndg_gate(pages, raw_headers=raw_headers)
    # P5 is warning-only → batch should still pass (no blockers)
    p5_issues = [i for i in report.issues if i.code == "P5"]
    assert len(p5_issues) == 1
    assert all(not i.is_blocker for i in p5_issues)
    assert report.passed  # P5 alone doesn't block
