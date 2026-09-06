from src.kc.views.book.wiki.cross_links import build_cross_link_candidates


def test_cross_links_are_manifest_candidates_with_existing_endpoints_only():
    outline = {"cross_link_candidates": [
        {"from_page": "p1", "to_page": "p2", "reason": "related"},
        {"from_page": "p1", "to_page": "missing", "reason": "bad"},
    ]}
    assert build_cross_link_candidates(outline, {"p1", "p2"}) == [
        {"from_page": "p1", "to_page": "p2", "reason": "related"}
    ]
