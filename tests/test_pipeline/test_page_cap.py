"""Tests for the page-count cap guard (_apply_page_cap_note).

batch-10/50 regression: per-doc page count varies 4-17 with no guard;
a 3.5KB doc produced 17 pages. The cap surfaces the anomaly in the
source page instead of silently inflating the index.
"""
from src.pipeline.ingest import _apply_page_cap_note
from src.wiki.core.types import PageType, WikiPage


def _page(pid: str, ptype: PageType) -> WikiPage:
    return WikiPage(id=pid, title=pid, type=ptype, body="body")


def test_cap_under_limit_unchanged():
    pages = [_page("s", PageType.SOURCE), _page("c1", PageType.CONCEPT)]
    result = _apply_page_cap_note(pages, "doc.md", cap=15)
    assert result == pages
    assert pages[0].body == "body"  # untouched


def test_cap_over_limit_annotates_source_page(caplog):
    pages = [_page("s", PageType.SOURCE)] + [
        _page(f"c{i}", PageType.CONCEPT) for i in range(20)
    ]
    result = _apply_page_cap_note(pages, "big.md", cap=15)
    assert len(result) == 21  # pages are NOT dropped
    assert "页面数超限" in result[0].body
    assert "21" in result[0].body  # count surfaced
    assert any("over-split" in r.message or "页面数超限" in r.message for r in caplog.records)


def test_cap_over_limit_no_source_page_still_warns(caplog):
    pages = [_page(f"c{i}", PageType.CONCEPT) for i in range(20)]
    result = _apply_page_cap_note(pages, "no-source.md", cap=15)
    assert len(result) == 20  # no crash, nothing dropped
    assert all("页面数超限" not in p.body for p in result)
