import pytest

from src.pipeline.readiness_gate import validate_page_contract
from src.pipeline.readiness_gate import validate_candidate_contract
from src.templates.contract import TemplateContract
from src.knowledge.core.candidate import KnowledgeCandidate
from src.knowledge.core.object import KnowledgeType
from src.wiki.core.types import PageType, WikiPage


def _contract():
    return TemplateContract(
        template_id="t", template_version="1", template_hash="h",
        allowed_types=("concept",), slot_rules={"concept": ("definition",)},
        routes={"concept": "wiki/concepts"}, purpose="p",
    )


def test_template_gate_accepts_allowed_page():
    page = WikiPage(id="p", title="P", type=PageType.CONCEPT, body="definition")
    assert validate_page_contract(_contract(), page) == []


def test_template_gate_rejects_disallowed_page_type():
    page = WikiPage(id="p", title="P", type=PageType.SOURCE, body="body")
    with pytest.raises(ValueError, match="not allowed"):
        validate_page_contract(_contract(), page)


@pytest.mark.parametrize("knowledge_type", [
    KnowledgeType.DOCUMENT,
    KnowledgeType.CLAIM,
    KnowledgeType.DECISION,
    KnowledgeType.PROCEDURE,
    KnowledgeType.EVENT,
])
def test_template_gate_maps_knowledge_candidate_to_page_type(knowledge_type):
    candidate = KnowledgeCandidate(
        id="c", source_id="raw/sources/test.md", type=knowledge_type,
        title="Test", claims=[], confidence=1.0, evidence=[], raw_llm_output={},
    )
    contract = TemplateContract(
        template_id="t", template_version="1", template_hash="h",
        allowed_types=("source", "concept"),
        slot_rules={"source": (), "concept": ()},
        routes={"source": "wiki/sources", "concept": "wiki/concepts"}, purpose="p",
    )
    assert validate_candidate_contract(contract, candidate) == []
