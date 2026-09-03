from types import SimpleNamespace

import pytest

from src.pipeline.publish_manifest import CommitError, commit_bundle
from src.wiki.core.paths import WikiPaths
from src.wiki.core.types import PageType, WikiPage


def _page(page_id: str) -> WikiPage:
    return WikiPage(id=page_id, title=page_id, type=PageType.CONCEPT, body="body")


def test_commit_rolls_back_when_second_page_fails(tmp_path):
    paths = WikiPaths(tmp_path)
    calls = []

    def writer(_paths, page, expected_content_hash=None):
        calls.append(page.id)
        if page.id == "second":
            raise OSError("disk full")

    context = SimpleNamespace(project_root=tmp_path, task_id="task-1", run_id="run-1", source_hash="hash", paths=paths, writer=writer)
    bundle = SimpleNamespace(task_id="task-1", source_id="source-1", bundle_hash="bundle", pages=(_page("first"), _page("second")))
    with pytest.raises(CommitError):
        commit_bundle(bundle, context)
    assert not (paths.wiki_concepts / "first.md").exists()
    assert not (paths.wiki_concepts / "second.md").exists()
    assert calls == ["first", "second"]
