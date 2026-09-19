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


# ---------------------------------------------------------------------------
# Relation-vocabulary drift guard (2026-09-19)
#
# The accepted-type set used to live in three hand-maintained copies that had
# drifted: generator.RELATION_TYPES (23, the write side), lint's private
# _BUILTIN_RELATIONS (21, missing refines/refined_by) and RelationType (19).
# Because lint's copy decides PAGE legality, `refines` was writable by the
# generator yet reported illegal by lint — and the batch gate, sharing the same
# constant, blocked whole batches. Everything now derives from
# relations.BUILTIN_RELATION_TYPES; the assertions below fail loudly if a
# private copy is re-introduced or one side evolves alone.
# ---------------------------------------------------------------------------


def test_builtin_relation_types_is_single_source_of_truth():
    from src.pipeline.generator import RELATION_TYPES
    from src.wiki.features import lint
    from src.wiki.features.relations import BUILTIN_RELATION_TYPES

    assert set(RELATION_TYPES) == set(BUILTIN_RELATION_TYPES)
    assert set(lint._BUILTIN_RELATIONS) == set(BUILTIN_RELATION_TYPES)
    # Guards the enum list against accidental duplicates / reordering bugs.
    assert len(RELATION_TYPES) == len(set(RELATION_TYPES))


def test_every_relation_type_enum_member_is_accepted():
    from src.wiki.features.relations import BUILTIN_RELATION_TYPES

    missing = {t.value for t in RelationType} - set(BUILTIN_RELATION_TYPES)
    assert not missing, f"RelationType members not accepted: {sorted(missing)}"


def test_every_inverse_relation_is_accepted():
    """``Relation.inverse()`` reads INVERSE_RELATIONS. If a pair member is not
    in the accepted set, the inverse edge that gets written onto the TARGET
    page is then reported illegal by lint."""
    from src.wiki.features.relations import BUILTIN_RELATION_TYPES, INVERSE_RELATIONS

    missing = set(INVERSE_RELATIONS) - set(BUILTIN_RELATION_TYPES)
    assert not missing, f"INVERSE_RELATIONS members not accepted: {sorted(missing)}"


def test_refines_and_refined_by_are_accepted():
    from src.wiki.features.relations import BUILTIN_RELATION_TYPES

    assert "refines" in BUILTIN_RELATION_TYPES
    assert "refined_by" in BUILTIN_RELATION_TYPES


def test_namespace_relation_types_are_accepted():
    """The 4 domain relation types live in their own literal
    (NAMESPACE_RELATION_TYPES) and are attached by ingest/schema routing, so
    nothing derives them from RelationType. Without this assertion, dropping
    one (e.g. taxonomy_of, written by ingest's taxonomy edges) would silently
    make every taxonomy_of edge illegal to lint."""
    from src.wiki.features.relations import (
        BUILTIN_RELATION_TYPES,
        NAMESPACE_RELATION_TYPES,
    )

    expected = {
        "taxonomy_of",
        "belongs_to_audience",
        "hosted_on_platform",
        "has_credibility",
    }
    assert set(NAMESPACE_RELATION_TYPES) == expected
    assert expected <= set(BUILTIN_RELATION_TYPES)
