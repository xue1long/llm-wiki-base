"""Regression tests for the P0 cross-reference fixes in run_ingest.

These exercise the REAL helpers (not copies) from src/pipeline/ingest.py and
src/wiki/features/relations.py:

  B9  - analyzer/generator now receive a built existing-wiki index.
  B10 - body [[wikilinks]] are scanned for stub/reference discovery.
  B11 - stub de-dup uses the real typed-dir scan (ENTITY/SYNTHESIS were missed
        by the old f"wiki_{pt.value}s" AttributeError path).
  B12 - Relation.from_dict slugifies the target so it matches page ids.
  B13 - _compute_reverse_relations writes inverse edges so the graph is
        bidirectional on disk (no RelationSync clobber).
"""
from pathlib import Path

from src.wiki.core.types import PageType, WikiPage
from src.wiki.core.paths import WikiPaths
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.storage.page_writer import write_page
from src.wiki.features.relations import Relation

from src.pipeline.ingest import (
    _collect_existing_wiki,
    _format_wiki_index,
    _extract_wikilink_targets,
    _compute_reverse_relations,
    _classify_missing_stubs,
    _is_source_slug_variant,
)


# ---------------------------------------------------------------------------
# B9 / B11: existing-wiki scan across all four typed directories
# ---------------------------------------------------------------------------
def test_collect_existing_wiki_covers_all_four_types(tmp_path: Path):
    """B11 regression: ENTITY and SYNTHESIS pages must be indexed.

    The old implementation built attribute names via f"wiki_{pt.value}s"
    (yielding wiki_entitys / wiki_synthesiss) which raised AttributeError and
    silently dropped those slugs. This test writes one page of every type and
    asserts the scan returns all four with the correct PageType.
    """
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    write_page(p, WikiPage(id="src-1", title="S", type=PageType.SOURCE, body=""))
    write_page(p, WikiPage(id="ent-1", title="E", type=PageType.ENTITY, body=""))
    write_page(p, WikiPage(id="con-1", title="C", type=PageType.CONCEPT, body=""))
    write_page(p, WikiPage(id="syn-1", title="Y", type=PageType.SYNTHESIS, body=""))

    index = _collect_existing_wiki(p)
    assert set(index) == {"src-1", "ent-1", "con-1", "syn-1"}
    assert index["ent-1"] is PageType.ENTITY
    assert index["syn-1"] is PageType.SYNTHESIS
    assert index["con-1"] is PageType.CONCEPT
    assert index["src-1"] is PageType.SOURCE


def test_format_wiki_index_empty_and_populated():
    assert _format_wiki_index({}) == "(empty)"
    out = _format_wiki_index({"ent-1": PageType.ENTITY, "con-1": PageType.CONCEPT})
    assert "- ent-1 (entity)" in out
    assert "- con-1 (concept)" in out


# ---------------------------------------------------------------------------
# B10: body wikilink extraction
# ---------------------------------------------------------------------------
def test_extract_wikilink_targets():
    """B10 regression: the original regex captured the alias text instead of
    the target for `[[Baz|alias text]]`. Non-greedy match + alias/section
    strip must yield the real target slug."""
    body = (
        "See [[Baz]] and [[Qux|alias text]] and [[Corge#section]] "
        "and [[  spaced  ]] plus a [[Nested|Display]] link."
    )
    targets = _extract_wikilink_targets(body)
    assert targets == ["Baz", "Qux", "Corge", "spaced", "Nested"]

    # plain text -> no links
    assert _extract_wikilink_targets("no links here") == []
    # empty body safe
    assert _extract_wikilink_targets("") == []
    assert _extract_wikilink_targets(None) == []


# ---------------------------------------------------------------------------
# B12: Relation target slug normalisation (real module)
# ---------------------------------------------------------------------------
def test_relation_from_dict_slugify():
    """B12: targets are normalised to the slug form used for page ids, and the
    operation is idempotent / CJK-preserving."""
    cjk = Relation.from_dict({"target": "佛本是道", "type": "references"})
    assert cjk.target_id == "佛本是道"

    ascii_rel = Relation.from_dict({"target": "Fo-Ben-Shi-Dao", "type": "references"})
    assert ascii_rel.target_id == "fo-ben-shi-dao"

    already = Relation.from_dict({"target": "fo-ben-shi-dao", "type": "references"})
    assert already.target_id == "fo-ben-shi-dao"
    assert ascii_rel.target_id == already.target_id  # idempotent

    inv = cjk.inverse()
    assert inv is not None and inv.type == "referenced_by"


# ---------------------------------------------------------------------------
# B13: bidirectional inverse-edge computation
# ---------------------------------------------------------------------------
def test_compute_reverse_relations_preexisting_target(tmp_path: Path):
    """A new page references a pre-existing page on disk -> the pre-existing
    page gets an inverse edge (returned as an extra page to write)."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    write_page(p, WikiPage(id="B-old", title="B", type=PageType.ENTITY, body="",
                           relations=[]))

    A = WikiPage(id="A", title="A", type=PageType.SOURCE, body="",
                 relations=[Relation(target_id="B-old", type="references")])
    extra = _compute_reverse_relations(p, [A])

    b = next((pg for pg in extra if pg.id == "B-old"), None)
    assert b is not None, "pre-existing target must be returned for writing"
    invs = [r for r in b.relations if r.target_id == "A"]
    assert len(invs) == 1
    assert invs[0].type == "referenced_by"


def test_compute_reverse_relations_new_target_mutated_in_place(tmp_path: Path):
    """A new page references another page created in the same run -> that page
    is mutated in place (not returned as extra), since the caller already
    writes `pages`."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)

    A = WikiPage(id="A", title="A", type=PageType.SOURCE, body="",
                 relations=[Relation(target_id="D", type="references")])
    D = WikiPage(id="D", title="D", type=PageType.ENTITY, body="", relations=[])

    extra = _compute_reverse_relations(p, [A, D])
    assert extra == []  # no pre-existing targets touched
    invs = [r for r in D.relations if r.target_id == "A"]
    assert len(invs) == 1 and invs[0].type == "referenced_by"


def test_compute_reverse_relations_dedupe_and_no_clobber(tmp_path: Path):
    """Two pages referencing the same pre-existing target must both get an
    inverse edge (no clobber), and a duplicate relation must not be added."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    write_page(p, WikiPage(id="B-old", title="B", type=PageType.ENTITY, body="",
                           relations=[]))

    A = WikiPage(id="A", title="A", type=PageType.SOURCE, body="",
                 relations=[Relation(target_id="B-old", type="references")])
    C = WikiPage(id="C", title="C", type=PageType.CONCEPT, body="",
                 relations=[Relation(target_id="B-old", type="references")])
    # also repeat A's edge in A itself to test de-dup within one page
    A2 = WikiPage(id="A", title="A", type=PageType.SOURCE, body="",
                  relations=[Relation(target_id="B-old", type="references"),
                             Relation(target_id="B-old", type="references")])

    extra = _compute_reverse_relations(p, [A, C, A2])
    b = next(pg for pg in extra if pg.id == "B-old")
    inv_targets = sorted(r.target_id for r in b.relations if r.type == "referenced_by")
    assert inv_targets == ["A", "C"]  # both edges, no duplicate A


def test_compute_reverse_relations_symmetric_skipped(tmp_path: Path):
    """Symmetric relations (e.g. contradicts) must NOT generate an inverse
    edge — the forward edge already represents both directions."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    write_page(p, WikiPage(id="B-old", title="B", type=PageType.ENTITY, body="",
                           relations=[]))

    A = WikiPage(id="A", title="A", type=PageType.SOURCE, body="",
                 relations=[Relation(target_id="B-old", type="contradicts")])
    extra = _compute_reverse_relations(p, [A])
    b = next((pg for pg in extra if pg.id == "B-old"), None)
    assert b is None or all(r.type != "contradicts" for r in b.relations)


# ---------------------------------------------------------------------------
# 0.5.1: missing-slug classification — stub suppression for non-domain refs
# ---------------------------------------------------------------------------
def test_classify_suppresses_source_slug_variant():
    """A slug whose 8-hex tail matches a real source page's hash is a broken
    source-page reference -> suppressed, no stub."""
    missing = {"必备资料-22-期待感让你的作品能够引人入胜-1-3deff6a3"}
    create, suppressed = _classify_missing_stubs(missing, {"3deff6a3"})
    assert suppressed == missing
    assert create == set()


def test_classify_source_variant_without_matching_hash_is_clean():
    """An 8-hex tail that does NOT match any real source hash is not a source
    variant (hard criterion, not loose stem match) -> treated as a clean
    referenced entity."""
    missing = {"some-entity-12345678"}
    create, suppressed = _classify_missing_stubs(missing, set())
    assert "some-entity-12345678" in create
    assert suppressed == set()


def test_classify_suppresses_tag_like_slugs():
    """Tag-namespace names (current CJK + legacy English) referenced as pages
    must not become stubs."""
    missing = {"func-教程", "题材-玄幻", "genre-现言", "event-冲突"}
    create, suppressed = _classify_missing_stubs(missing, set())
    assert suppressed == missing
    assert create == set()


def test_classify_suppresses_type_prefix_and_entity_suffix():
    """PageType-prefixed ids and `-entity` suffix must not become stubs."""
    missing = {
        "source-补充教程小说写作大纲的模版共享-a56031f5",
        "concept-穿越小说角色塑造套路",
        "琴帝-entity",
    }
    create, suppressed = _classify_missing_stubs(missing, set())
    assert suppressed == missing
    assert create == set()


def test_classify_suppresses_path_like_slugs():
    """Raw-path slugs (double hyphen / raw- prefix / -md-) must not become
    stubs."""
    missing = {
        "raw-sources-01-新手入门--入门教程三十六种经典情节模式情节艺术-md-9163987c",
        "女频男频--架空类小说恶俗桥段盘点-8a5397b6",
    }
    create, suppressed = _classify_missing_stubs(missing, set())
    assert suppressed == missing
    assert create == set()


def test_classify_creates_clean_referenced_entities():
    """Genuine entity references (clean slugs) still get a stub (subject to
    the cap) — suppression must not hide real missing entities."""
    missing = {"tolkien", "修真", "an-yi"}
    create, suppressed = _classify_missing_stubs(missing, set())
    assert create == missing
    assert suppressed == set()


def test_is_source_slug_variant_hard_criterion():
    """Only an exact hash-tail match suppresses; a different tail or no tail
    does not."""
    slug = "必备资料22期待感让你的作品能够引人入胜1-3deff6a3"
    assert _is_source_slug_variant(slug, {"3deff6a3"})
    assert not _is_source_slug_variant(slug, {"deadbeef"})
    assert not _is_source_slug_variant("tolkien", {"3deff6a3"})
