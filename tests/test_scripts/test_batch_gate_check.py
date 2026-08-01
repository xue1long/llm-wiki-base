"""NDG Phase 6 (fix C): batch_gate_check reconcile integration tests.

batch_gate_check.py reads *on-disk* wiki pages and runs the NDG gate on
them.  Since it bypasses phase4_batch (which runs reconcile_batch before
the gate), it must run reconcile itself so that cross-type slug conflicts
the wiki has already adjudicated are not mis-flagged by P6.
"""
import sys
from pathlib import Path

import pytest

from src.wiki.core.paths import WikiPaths
from src.wiki.core.types import PageType, WikiPage
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.storage.page_writer import write_page


def _make_wiki(root: Path, index_entries: list[tuple[str, PageType]]) -> WikiPaths:
    """Build a wiki project with the given index entries (slug → type) and
    return its WikiPaths."""
    paths = ensure_knowledge_base(root)
    idx_lines = ["# Wiki Index\n"]
    for slug, ptype in index_entries:
        idx_lines.append(f"- **{slug}** ({ptype.value}) — {slug}\n")
    paths.llm_wiki_index.write_text("".join(idx_lines), encoding="utf-8")
    return paths


def _page(slug: str, ptype: PageType, body: str = "body") -> WikiPage:
    # sources set so P3 (input→source pairing) doesn't fire on clean pages.
    return WikiPage(
        id=slug, title=slug, type=ptype, body=body,
        sources=["raw/sources/test.md"],
    )


def _rel_page_arg(root: Path, page: WikiPage, paths: WikiPaths) -> str:
    """Write a page to disk and return its path relative to root (the form
    batch_gate_check.main expects after ``wiki_root / p``)."""
    write_page(paths, page)
    from src.wiki.storage.page_writer import page_path_for
    return page_path_for(paths, page.type, page.id).relative_to(root).as_posix()


# ---------------------------------------------------------------------------
# Wiki-known cross-type conflict → reconciled, gate passes
# ---------------------------------------------------------------------------

def test_main_reconciles_wiki_known_cross_type(tmp_path: Path, monkeypatch):
    """Wiki declares 三清 as concept; disk has an ENTITY and a CONCEPT page
    with that slug.  Reconcile drops the entity page (wiki wins), so P6 has
    nothing to flag → exit 0."""
    paths = _make_wiki(tmp_path, [("三清", PageType.CONCEPT)])
    ent = _page("三清", PageType.ENTITY, body="entity ver")
    con = _page("三清", PageType.CONCEPT, body="concept ver")
    e_rel = _rel_page_arg(tmp_path, ent, paths)
    c_rel = _rel_page_arg(tmp_path, con, paths)

    rc = _run_main(monkeypatch, tmp_path, [e_rel, c_rel])
    assert rc == 0, f"wiki-known cross-type must pass after reconcile, got rc={rc}"


# ---------------------------------------------------------------------------
# Wiki-unknown cross-type conflict → still blocked
# ---------------------------------------------------------------------------

def test_main_blocks_wiki_unknown_cross_type(tmp_path: Path, monkeypatch):
    """Wiki has no entry for 新实体; disk has ENTITY + CONCEPT pages with that
    slug.  Reconcile cannot pick a side → conflict reported → exit 1."""
    paths = _make_wiki(tmp_path, [])
    ent = _page("新实体", PageType.ENTITY, body="e")
    con = _page("新实体", PageType.CONCEPT, body="c")
    e_rel = _rel_page_arg(tmp_path, ent, paths)
    c_rel = _rel_page_arg(tmp_path, con, paths)

    rc = _run_main(monkeypatch, tmp_path, [e_rel, c_rel])
    assert rc == 1, f"wiki-unknown cross-type must still block, got rc={rc}"


# ---------------------------------------------------------------------------
# Clean batch → pass
# ---------------------------------------------------------------------------

def test_main_passes_clean_batch(tmp_path: Path, monkeypatch):
    """No slug collisions → gate passes → exit 0."""
    paths = _make_wiki(tmp_path, [])
    a = _page("甲", PageType.ENTITY, body="a")
    b = _page("乙", PageType.CONCEPT, body="b")
    a_rel = _rel_page_arg(tmp_path, a, paths)
    b_rel = _rel_page_arg(tmp_path, b, paths)

    rc = _run_main(monkeypatch, tmp_path, [a_rel, b_rel])
    assert rc == 0, f"clean batch must pass, got rc={rc}"


# ---------------------------------------------------------------------------
# helper
# ---------------------------------------------------------------------------

def _run_main(monkeypatch, root: Path, rel_pages: list[str]) -> int:
    """Invoke scripts.batch_gate_check.main with the given page args."""
    from scripts.batch_gate_check import main
    argv = [str(root)] + rel_pages
    return main(argv)
