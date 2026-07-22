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


def test_relation_type_enum_has_built_ins():
    """RelationType enum has 17 built-in relation types (plan said 16 — typo)."""
    assert len(RelationType) == 17
    # Spot-check a few
    assert RelationType.REFERENCES.value == "references"
    assert RelationType.IS_PART_OF.value == "is_part_of"
    assert RelationType.DERIVES.value == "derives"