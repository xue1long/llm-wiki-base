from types import SimpleNamespace

import pytest
import hashlib

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


def test_commit_quarantines_manual_version_conflict(tmp_path):
    paths = WikiPaths(tmp_path)
    page = _page("existing")
    target = paths.wiki_concepts / "existing.md"
    target.parent.mkdir(parents=True)
    target.write_text("manual edit", encoding="utf-8")
    context = SimpleNamespace(
        project_root=tmp_path, task_id="task-2", run_id="run-2", source_hash="hash", paths=paths,
        expected_versions={"existing": hashlib.sha256(b"old content").hexdigest()},
    )
    bundle = SimpleNamespace(task_id="task-2", source_id="source-1", bundle_hash="bundle", pages=(page,))
    result = commit_bundle(bundle, context)
    assert result.status == "quarantined"
    assert target.read_text(encoding="utf-8") == "manual edit"
