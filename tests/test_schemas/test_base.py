from pydantic import Field

from src.schemas.base import ForwardCompatModel


def test_forward_compat_preserves_unknown_fields():
    """Unknown fields are kept on instance after parse."""
    class PageV1(ForwardCompatModel):
        id: str
        title: str

    # Parse data with unknown field
    page = PageV1.model_validate({"id": "abc", "title": "Test", "future_field": 42})
    assert page.id == "abc"
    assert page.title == "Test"
    # Unknown field preserved
    assert hasattr(page, "future_field")
    assert page.future_field == 42


def test_forward_compat_round_trip():
    """to_yaml_compatible() → from_yaml_compatible() preserves all fields."""
    class PageV1(ForwardCompatModel):
        id: str
        title: str

    page = PageV1.model_validate({"id": "x", "title": "y", "custom": "z"})
    data = page.to_yaml_compatible()
    restored = PageV1.from_yaml_compatible(data)
    assert restored.id == "x"
    assert restored.title == "y"
    assert restored.custom == "z"


def test_forward_compat_strict_mode_optional():
    """Subclass can override to extra='forbid' for strict schema."""
    from pydantic import ConfigDict

    class StrictPage(ForwardCompatModel):
        model_config = ConfigDict(extra="forbid")
        id: str

    import pytest
    with pytest.raises(Exception):
        StrictPage.model_validate({"id": "x", "extra": "no"})
