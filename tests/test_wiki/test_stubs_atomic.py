"""Tests for atomic-context behaviour of stub materialization.

Verifies I-pipeline-3 fix: stub removal goes through safe_write + DELETE_SENTINEL
so it's batched into the AtomicContext commit point (no premature os.unlink).
"""
import pytest

from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.features.stubs import StubMaterializerWorker
from src.lib.atomic_ctx import AtomicContext, __reset_for_testing
from src.lib import write_hooks
from src.lib.write_hooks import DELETE_SENTINEL


def setup_function(_):
    __reset_for_testing()
    write_hooks._reset_for_testing()


def test_stub_unlink_uses_sentinel(tmp_path):
    """Inside AtomicContext, stub removal queues a DELETE_SENTINEL, not os.unlink."""
    ensure_knowledge_base(tmp_path)
    stub = tmp_path / "wiki" / "_stubs" / "foo.md"
    stub.parent.mkdir(parents=True, exist_ok=True)
    stub.write_text(
        "---\nid: foo\ntitle: Foo\ntype: stub\n---\n",
        encoding="utf-8",
    )
    real = tmp_path / "wiki" / "sources" / "foo.md"

    # The materialization worker expects a ScriptedLLMProvider that produces
    # a real page — so wire up one and call it inside an AtomicContext.
    from src.shared.test_helpers import ScriptedLLMProvider

    provider = ScriptedLLMProvider([
        {"pages": [
            {"id": "foo", "type": "concept", "title": "Foo Real",
             "frontmatter_extra": {},
             "slots": {"definition": "Real body.",
                       "characteristics": ["c"], "examples": ["e"],
                       "related_concepts": ["rc"], "references": ["r"]}},
        ]}
    ])

    # Ensure real target does not pre-exist
    if real.exists():
        real.unlink()

    # Reference the stub from a source page so _find_referenced_stubs finds it
    from src.wiki.storage.page_writer import write_page
    from src.wiki.core.types import WikiPage, PageType
    from src.wiki.core.paths import WikiPaths
    paths = WikiPaths(tmp_path)
    # write_page here runs OUTSIDE an AtomicContext, so it actually commits
    write_page(paths, WikiPage(
        id="referrer", title="Referrer", type=PageType.ENTITY,
        body="see [[foo]] for context",
    ))

    worker = StubMaterializerWorker(paths, provider)

    # The stub path used by the worker
    stub_via_worker = paths.wiki_stubs / "foo.md"
    # Confirm worker sees it
    refs = worker._find_referenced_stubs()
    assert "foo" in refs

    with AtomicContext():
        # Materialize synchronously inside an atomic context.
        # The worker is async — we drive it inline.
        import asyncio
        result = asyncio.run(worker._materialize_one("foo"))
        assert result is True

    # _pending_writes should contain DELETE_SENTINEL keyed by the stub path
    pending = write_hooks._current_bucket()
    found_sentinel = any(v is DELETE_SENTINEL for v in pending.values())
    assert found_sentinel, (
        f"Expected DELETE_SENTINEL in pending bucket, got {pending}"
    )

    # On disk: nothing committed yet (real page write is also deferred via
    # write_page → safe_write; only on flush would it land). The stub still
    # exists on disk because the DELETE_SENTINEL is buffered.
    assert stub_via_worker.exists()
    assert not real.exists()

