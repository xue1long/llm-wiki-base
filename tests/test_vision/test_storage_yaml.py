"""Regression: vision media-page frontmatter must survive yaml.safe_load
even when caption / alt_text contains YAML-significant characters.
"""
import yaml


def test_vision_frontmatter_yaml_roundtrip_with_quotes():
    """Mirror _build_frontmatter's dict and verify round-trip."""
    fm_dict = {
        "id": "task1_0",
        "title": "Image from task1",
        "type": "media",
        "sources": ["raw/sources/task1.pdf"],
        "caption": "shows: a thing \"quoted\" with: colons",
        "alt_text": "an # anchor and ? query",
        "entities": ["Alice", "Bob"],
        "confidence": 0.92,
        "image": "media/task1_0.png",
        "created_at": 1700000000000,
        "updated_at": 1700000000000,
        "grade": "B",
        "processing_depth": "concept",
        "is_immutable": False,
    }
    import yaml as pyyaml
    fm_yaml = "---\n" + pyyaml.dump(
        fm_dict, allow_unicode=True, sort_keys=False, default_flow_style=False
    ) + "---\n"
    body = fm_yaml.replace("---", "", 2).strip()
    parsed = yaml.safe_load(body)
    assert parsed == fm_dict, (
        f"yaml round-trip must preserve dict exactly; got {parsed!r}"
    )
