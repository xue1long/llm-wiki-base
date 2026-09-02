import pytest

from src.pipeline.readiness_gate import validate_page_contract
from src.templates.contract import TemplateContract
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
