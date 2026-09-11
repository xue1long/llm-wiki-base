"""Regression checks for the minimal Wiki/Vector ready state."""

from src.vector import pending
from src.wiki.core.paths import WikiPaths
from src.wiki.core.types import PageType, WikiPage
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.storage.page_writer import write_page


def test_ready_requires_vector_hash_and_model_match(tmp_path):
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    page = WikiPage(id="ready-page", title="Ready", type=PageType.CONCEPT, body="body")
    write_page(paths, page)
    pending.mark_pending(paths, [page])

    assert pending.readiness(paths, embedding_model="test-model")["ready"] is False

    result = pending.reconcile_pending(
        paths,
        lambda *_args, **_kwargs: {
            "vector_content_hash": pending.body_hash(page.body),
            "embedding_model": "test-model",
        },
    )
    assert result["ok"] == 1
    assert pending.readiness(paths, embedding_model="test-model")["ready"] is True
    assert pending.readiness(paths, embedding_model="other-model")["ready"] is False


def test_failed_vector_publication_is_not_ready(tmp_path):
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    page = WikiPage(id="failed-page", title="Failed", type=PageType.CONCEPT, body="body")
    write_page(paths, page)
    pending.mark_pending(paths, [page])
    pending.reconcile_pending(paths, lambda *_args, **_kwargs: False)

    status = pending.readiness(paths, embedding_model="test-model")
    assert status["ready"] is False
    assert status["reason"] == "failed"
