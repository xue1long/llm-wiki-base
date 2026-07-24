"""Regression: research synthesis frontmatter must survive yaml.safe_load
even when topic contains YAML-significant characters.

The old implementation concatenated frontmatter with f-strings, which
broke yaml.safe_load for topics containing ':' (parsed as two keys)
or '"' (parsed as unterminated string).
"""
import yaml


def test_research_frontmatter_yaml_roundtrip_with_quotes():
    """Build the same fm_dict the runner builds and round-trip it."""
    fm_dict = {
        "id": "research-topic-x-2026-07-25",
        "title": "Research: Topic X: a deep dive (with quotes \"y\")",
        "type": "synthesis",
        "sources": ["https://example.com/a?x=1#frag"],
        "created_at": 1700000000000,
        "updated_at": 1700000000000,
        "grade": "B",
        "processing_depth": "concept",
        "is_immutable": False,
        "research_task_id": "research-topic-x-2026-07-25",
    }
    import yaml as pyyaml
    fm_yaml = (
        "---\n"
        + pyyaml.dump(fm_dict, allow_unicode=True, sort_keys=False, default_flow_style=False)
        + "---\n"
    )
    # Strip --- delimiters
    body = fm_yaml.replace("---", "", 2).strip()
    parsed = yaml.safe_load(body)
    assert parsed == fm_dict, (
        f"yaml round-trip must preserve dict exactly; got {parsed!r}"
    )
