"""Task 1.8 — GeneratorOutputValidator: enforce render-only constraint.

The Generator's role is to render the body via LLM; frontmatter fields
MUST be copied from the input KnowledgeObject.  This validator catches
LLM hallucination in frontmatter (invented fields, modified facts, extra
knowledge not in the candidate).
"""
import pytest

from src.knowledge.core.object import KnowledgeObject, KnowledgeType, LifecycleState, Provenance
from src.pipeline.generator_constraint import GeneratorOutputValidator
from src.wiki.core.types import PageType, WikiPage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ko(**overrides) -> KnowledgeObject:
    """Minimal valid KnowledgeObject for testing."""
    defaults = {
        "id": "test-concept-1",
        "type": KnowledgeType.CONCEPT,
        "title": "测试概念",
        "content": "这是一个测试概念的定义。",
        "lifecycle": LifecycleState.PROCESSING,
        "confidence": 0.85,
        "provenance": Provenance(
            source_path="raw/sources/test.md",
            page=1,
            quote="原始文本",
            ingested_at=1720000000000,
        ),
        "grade": "B",
        "heat": 55,
        "relations": [],
        "created_at": 1720000000000,
        "updated_at": 1720000000001,
    }
    defaults.update(overrides)
    return KnowledgeObject(**defaults)


def _wp(**overrides) -> WikiPage:
    """Minimal WikiPage whose frontmatter matches the default _ko()."""
    defaults = {
        "id": "test-concept-1",
        "title": "测试概念",
        "type": PageType.CONCEPT,
        "sources": ["raw/sources/test.md"],
        "created_at": 1720000000000,
        "updated_at": 1720000000001,
        "body": "## 定义\n\n这是一个测试概念的定义。",
        "grade": "B",
        "heat": 55,
        "relations": [],
        "tags": [],
        "category": "",
        "taxonomy_sub": "",
    }
    defaults.update(overrides)
    return WikiPage(**defaults)


# ---------------------------------------------------------------------------
# 1. Valid output passes
# ---------------------------------------------------------------------------

def test_validator_accepts_valid_output():
    """GeneratorOutputValidator accepts a WikiPage whose frontmatter matches KnowledgeObject."""
    ko = _ko()
    wp = _wp()
    errors = GeneratorOutputValidator.validate(ko, wp)
    assert errors == [], f"expected no errors, got: {errors}"


def test_validator_accepts_empty_body():
    """Empty body is acceptable — Generator may produce a stub."""
    ko = _ko()
    wp = _wp(body="")
    errors = GeneratorOutputValidator.validate(ko, wp)
    assert errors == [], f"expected no errors for empty body, got: {errors}"


# ---------------------------------------------------------------------------
# 2. Frontmatter fields must match KnowledgeObject
# ---------------------------------------------------------------------------

def test_validator_rejects_id_mismatch():
    """WikiPage id must match KnowledgeObject id."""
    ko = _ko(id="ko-id-123")
    wp = _wp(id="wp-id-456")
    errors = GeneratorOutputValidator.validate(ko, wp)
    assert len(errors) >= 1
    assert any("id" in e.lower() for e in errors), errors


def test_validator_rejects_title_mismatch():
    """WikiPage title must match KnowledgeObject title."""
    ko = _ko(title="原始标题")
    wp = _wp(title="修改后的标题")
    errors = GeneratorOutputValidator.validate(ko, wp)
    assert len(errors) >= 1
    assert any("title" in e.lower() for e in errors), errors


def test_validator_rejects_grade_change():
    """Grade must not be modified — Guard against LLM inflating grades."""
    ko = _ko(grade="C")
    wp = _wp(grade="A")
    errors = GeneratorOutputValidator.validate(ko, wp)
    assert len(errors) >= 1
    assert any("grade" in e.lower() for e in errors), errors


def test_validator_rejects_heat_change():
    """Heat must not be modified by Generator."""
    ko = _ko(heat=30)
    wp = _wp(heat=90)
    errors = GeneratorOutputValidator.validate(ko, wp)
    assert len(errors) >= 1
    assert any("heat" in e.lower() for e in errors), errors


def test_validator_rejects_type_mismatch():
    """WikiPage PageType must derive from KnowledgeObject KnowledgeType."""
    ko = _ko(type=KnowledgeType.ENTITY)
    wp = _wp(type=PageType.CONCEPT, title="测试实体")
    errors = GeneratorOutputValidator.validate(ko, wp)
    assert len(errors) >= 1
    assert any("type" in e.lower() for e in errors), errors


def test_validator_rejects_sources_missing_provenance():
    """WikiPage.sources must contain KnowledgeObject.provenance.source_path."""
    ko = _ko(provenance=Provenance(
        source_path="raw/sources/original.md",
        page=1,
        quote="text",
    ))
    wp = _wp(sources=["raw/sources/wrong.md"])
    errors = GeneratorOutputValidator.validate(ko, wp)
    assert len(errors) >= 1
    assert any("source" in e.lower() for e in errors), errors


def test_validator_rejects_timestamp_mismatch():
    """WikiPage created_at / updated_at must match KnowledgeObject."""
    ko = _ko(created_at=100000, updated_at=200000)
    wp = _wp(created_at=999999, updated_at=888888)
    errors = GeneratorOutputValidator.validate(ko, wp)
    assert len(errors) >= 1
    assert any("created_at" in e.lower() for e in errors), errors


# ---------------------------------------------------------------------------
# 3. Modified facts / invented fields
# ---------------------------------------------------------------------------

def test_validator_rejects_modified_confidence_equivalent():
    """If WikiPage had a confidence field equivalent, changing it would be rejected.

    Confidence maps to grade implications: generator must not promote low-
    confidence knowledge to high-grade pages.
    """
    ko = _ko(confidence=0.3, grade="C")
    wp = _wp(grade="A")  # high grade for low-confidence knowledge
    errors = GeneratorOutputValidator.validate(ko, wp)
    assert len(errors) >= 1
    assert any("grade" in e.lower() for e in errors), errors


def test_validator_rejects_immutable_flag_set():
    """is_immutable should be False (default) — Generator must not set it."""
    ko = _ko()
    wp = _wp(is_immutable=True)
    errors = GeneratorOutputValidator.validate(ko, wp)
    assert len(errors) >= 1
    assert any("immutable" in e.lower() for e in errors), errors


# ---------------------------------------------------------------------------
# 4. Entity type acceptance
# ---------------------------------------------------------------------------

def test_validator_accepts_entity_type():
    """ENTITY KnowledgeObject maps to ENTITY PageType correctly."""
    ko = _ko(
        id="test-entity",
        type=KnowledgeType.ENTITY,
        title="测试实体",
    )
    wp = _wp(
        id="test-entity",
        type=PageType.ENTITY,
        title="测试实体",
    )
    errors = GeneratorOutputValidator.validate(ko, wp)
    assert errors == [], f"expected no errors for entity type, got: {errors}"


def test_validator_accepts_document_to_source_mapping():
    """DOCUMENT KnowledgeObject maps to SOURCE PageType."""
    ko = _ko(
        id="test-doc",
        type=KnowledgeType.DOCUMENT,
        title="测试文档",
    )
    wp = _wp(
        id="test-doc",
        type=PageType.SOURCE,
        title="测试文档",
    )
    errors = GeneratorOutputValidator.validate(ko, wp)
    assert errors == [], f"expected no errors for document->source mapping, got: {errors}"


# ---------------------------------------------------------------------------
# 5. All KnowledgeType to PageType mappings
# ---------------------------------------------------------------------------

def test_validator_type_mapping_table():
    """Every KnowledgeType has a valid PageType mapping."""
    from src.pipeline.generator_constraint import KO_TYPE_TO_PAGE_TYPE
    for kt in KnowledgeType:
        pt = KO_TYPE_TO_PAGE_TYPE.get(kt)
        assert pt is not None, f"KnowledgeType.{kt.name} has no PageType mapping"
        assert isinstance(pt, PageType), f"Mapping for {kt.name} is not a PageType: {pt!r}"


def test_validator_type_mapping_is_bijective():
    """Each KnowledgeType maps to a UNIQUE PageType (no two types share same mapping)."""
    from src.pipeline.generator_constraint import KO_TYPE_TO_PAGE_TYPE
    seen: dict[PageType, KnowledgeType] = {}
    for kt, pt in KO_TYPE_TO_PAGE_TYPE.items():
        if pt in seen:
            raise AssertionError(
                f"PageType.{pt.value} is mapped from both "
                f"KnowledgeType.{seen[pt].name} and KnowledgeType.{kt.name}"
            )
        seen[pt] = kt


# ---------------------------------------------------------------------------
# 6. Validator is importable and has expected public API
# ---------------------------------------------------------------------------

def test_validator_public_api():
    """GeneratorOutputValidator exposes validate(ko, wp) -> list[str]"""
    assert hasattr(GeneratorOutputValidator, "validate")
    errors = GeneratorOutputValidator.validate(_ko(), _wp())
    assert isinstance(errors, list)
    # All entries must be strings (error messages).
    for e in errors:
        assert isinstance(e, str), f"non-string error: {e!r}"
