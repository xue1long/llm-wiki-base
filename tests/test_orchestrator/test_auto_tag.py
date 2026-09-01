from types import SimpleNamespace

from src.orchestrator import batch_runner
from src.orchestrator.auto_tag import auto_tag_ugc


def page(sources, tags=None, processing_depth="concept"):
    return SimpleNamespace(
        sources=sources,
        tags=tags,
        processing_depth=processing_depth,
    )


def test_carrier_tags_are_in_place_and_ordered():
    item = page(["raw/ugc.md"], ["existing"])
    assert auto_tag_ugc([item], {"raw/ugc.md": "公众号整理"}) == 1
    assert item.tags == ["existing", "素材/ugc", "可信度/ugc"]


def test_stub_plain_and_duplicate_cases():
    stub = page(["raw/ugc.md"], [], "stub")
    tagged = page(["raw/ugc.md"], ["素材/ugc"])
    plain = page(["raw/plain.md"], [])
    assert auto_tag_ugc([stub, tagged, plain], {"raw/ugc.md": "公众号整理"}) == 1
    assert stub.tags == []
    assert tagged.tags == ["素材/ugc", "可信度/ugc"]
    assert plain.tags == []


def test_empty_headers_are_noop():
    item = page(["raw/ugc.md"], [])
    assert auto_tag_ugc([item], None) == 0
    assert item.tags == []


def test_facade_alias_is_preserved():
    assert batch_runner._auto_tag_ugc is auto_tag_ugc
