"""Tests for src.wiki.relations."""
from src.wiki.features.relations import (
    Relation, RelationType, INVERSE_RELATIONS, USER_TYPE_PREFIX,
)


def test_relation_round_trip():
    """Relation.to_dict() → from_dict() preserves all fields."""
    r = Relation(target_id="foo", type="references", weight=0.7, context="see also")
    d = r.to_dict()
    assert d["target"] == "foo"
    assert d["type"] == "references"
    assert d["weight"] == 0.7
    assert d["context"] == "see also"

    r2 = Relation.from_dict(d)
    assert r2.target_id == "foo"
    assert r2.type == "references"
    assert r2.weight == 0.7
    assert r2.context == "see also"


def test_inverse_known():
    """references ↔ referenced_by are inverses."""
    assert INVERSE_RELATIONS["references"] == "referenced_by"
    assert INVERSE_RELATIONS["referenced_by"] == "references"
    assert INVERSE_RELATIONS["is_part_of"] == "contains"
    assert INVERSE_RELATIONS["contains"] == "is_part_of"


def test_inverse_symmetric():
    """contradicts, analogous_to, opposite_of are symmetric (inverse == self)."""
    assert INVERSE_RELATIONS["contradicts"] == "contradicts"
    assert INVERSE_RELATIONS["analogous_to"] == "analogous_to"
    assert INVERSE_RELATIONS["opposite_of"] == "opposite_of"


def test_user_type_prefix():
    """USER_TYPE_PREFIX is 'x-' for user-defined types."""
    assert USER_TYPE_PREFIX == "x-"


def test_refines_inverse_relationship():
    """V7.1.1: ``refines`` / ``refined_by`` are inverse of each other."""
    assert INVERSE_RELATIONS["refines"] == "refined_by"
    assert INVERSE_RELATIONS["refined_by"] == "refines"
    # Inverse lookup via .inverse() method
    from src.wiki.features.relations import Relation
    r = Relation(target_id="target", type="refines", weight=0.9)
    inv = r.inverse()
    assert inv is not None
    assert inv.type == "refined_by"


def test_refines_relation_round_trip(tmp_path):
    """V7.1.1: ``refines`` relation survives write_page / read_page."""
    from src.wiki.core.types import PageType, WikiPage
    from src.wiki.storage.page_writer import write_page, read_page, page_path_for
    from src.wiki.storage.ensure import ensure_knowledge_base
    from src.wiki.core.paths import WikiPaths

    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    page = WikiPage(
        id="bai-lian-fa", title="百炼法", type=PageType.CONCEPT,
        relations=[Relation(target_id="kuo-ju-fa", type="refines",
                           weight=0.9, context="扩句法的细化")],
    )
    write_page(p, page)
    loaded = read_page(page_path_for(p, PageType.CONCEPT, "bai-lian-fa"))
    assert len(loaded.relations) == 1
    assert loaded.relations[0].type == "refines"
    assert loaded.relations[0].target_id == "kuo-ju-fa"


def test_relation_type_enum_has_built_ins():
    """RelationType enum has 19 built-in relation types as of V7.1.1.

    V7.1.1 (RFC v6) added ``refines`` / ``refined_by`` for parent→child
    method relationships. Previously the enum had 17 types.
    """
    assert len(RelationType) == 19
    # Spot-check a few
    assert RelationType.REFERENCES.value == "references"
    assert RelationType.IS_PART_OF.value == "is_part_of"
    assert RelationType.DERIVES.value == "derives"
    # V7.1.1 new relations
    assert RelationType.REFINES.value == "refines"
    assert RelationType.REFINED_BY.value == "refined_by"
