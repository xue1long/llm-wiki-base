"""Tests for atomic-context behaviour of dedup_auto record().

Verifies I-pipeline-4 fix: DedupHistoryStore.record() should go through
safe_write with DELETE_SENTINEL so deletions are deferred to commit time
when called inside an AtomicContext.
"""

from src.wiki.features.dedup_auto import DedupHistoryStore
from src.wiki.core.types import PageType, WikiPage
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.core.paths import WikiPaths
from src.wiki.storage.page_writer import write_page
from src.lib.atomic_ctx import AtomicContext, __reset_for_testing
from src.lib import write_hooks
from src.lib.write_hooks import DELETE_SENTINEL


def setup_function(_):
    __reset_for_testing()
    write_hooks._reset_for_testing()


def test_dedup_record_inside_atomic_context_uses_sentinel(tmp_path):
    """Inside AtomicContext, merged file removal uses DELETE_SENTINEL."""
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    write_page(paths, WikiPage(id="a", title="A", type=PageType.ENTITY, body="x"))
    write_page(paths, WikiPage(id="b", title="B", type=PageType.ENTITY, body="y"))

    # Confirm b.md exists on disk
    b_path = paths.wiki_entities / "b.md"
    assert b_path.exists()

    with AtomicContext():
        record = DedupHistoryStore.record(paths, canonical="a", merged=["b"], confidence="high")
        assert record.canonical_slug == "a"

    # After exiting AtomicContext (without a flush_callback), b.md must still exist
    # because the deletion was deferred via DELETE_SENTINEL, not os.unlink'd
    assert b_path.exists()

    # _pending_writes should have a DELETE_SENTINEL keyed by b_path
    pending = write_hooks._current_bucket()
    found_sentinel = any(v is DELETE_SENTINEL for v in pending.values())
    assert found_sentinel, (
        f"Expected DELETE_SENTINEL in pending bucket, got keys="
        f"{list(pending.keys())}"
    )
