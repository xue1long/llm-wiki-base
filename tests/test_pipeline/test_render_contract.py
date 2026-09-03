import pytest

from src.pipeline.render_contract import RenderBundle, RenderDraft, render_candidate


def test_render_draft_cannot_be_written_as_wikipage():
    draft = RenderDraft("t", "s", "p", 0, "tpl", "标题", "concept", "正文")
    assert not hasattr(draft, "evidence_id")
    assert not hasattr(draft, "page_id")


def test_bundle_is_stable_and_immutable():
    bundle = render_candidate({"source_id": "s", "title": "标题", "type": "concept", "body": "正文"}, {"task_id": "t", "template_version": "tpl"})
    assert bundle.bundle_hash == bundle.compute_hash()
    with pytest.raises(AttributeError):
        bundle.pages = ()


def test_page_key_is_not_array_identity():
    bundle = render_candidate({"source_id": "s", "pages": [{"page_key": "stable", "title": "标题", "type": "concept", "body": "正文"}]}, {"task_id": "t", "template_version": "tpl"})
    assert bundle.pages[0].page_key == "stable"
