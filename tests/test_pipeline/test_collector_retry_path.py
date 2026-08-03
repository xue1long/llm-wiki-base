"""Regression tests for the collector's read-and-don't-move contract.

After the 2026-07 Inbox-cleanup, the collector reads from
``raw/sources/<file>`` and **never** moves the source file. The pipeline
still relies on the file being at its original location for retries —
the previous ``move_to_processing`` flow would move the file before the
LLM stage and turn every transient LLM failure into a DEAD_LETTER.
"""
import asyncio



def test_collector_does_not_move_source_on_pipeline_failure(tmp_path, monkeypatch):
    """Drive collector.collect() through a downstream failure path and
    assert the source file is STILL at its original location.

    With the legacy Inbox-staged-copy flow, ``collect()`` used to call
    ``inbox.move_to_processing(source)`` synchronously after reading,
    which meant queue retries couldn't re-read the source (it had been
    moved). The fix is to never move the source from the collector —
    idempotency is handled by the md5 cache in
    ``src/utils/idempotency.py``.
    """
    monkeypatch.setattr(
        "src.pipeline.collector.enforce_permission",
        lambda *a, **kw: None,
    )

    source = tmp_path / "raw" / "sources" / "doc.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("hello world", encoding="utf-8")

    from src.pipeline.collector import collect
    from src.types import SourceType

    async def drive_and_fail():
        try:
            # Pass project-relative path; collector resolves against
            # project_root = tmp_path via the project_id branch — but we
            # didn't register a project here, so just use absolute path.
            await collect(
                task_id="test-task",
                source=str(source),
                source_type=SourceType.FILE,
            )
        except Exception:
            pass  # downstream stages will fail (no LLM wired)

    asyncio.run(drive_and_fail())

    assert source.exists(), (
        f"Source file at {source} was moved/deleted by collector. "
        "After the 2026-07 cleanup, collector must read and leave the "
        "source file in place. Idempotency is handled by the md5 cache, "
        "not by moving the file."
    )


def test_collector_does_not_write_staged_copy(tmp_path, monkeypatch):
    """The collector should NOT create any Inbox/Processing/<task_id>.md
    copy. The legacy flow staged a copy there; the cleanup removes that.
    """
    monkeypatch.setattr(
        "src.pipeline.collector.enforce_permission",
        lambda *a, **kw: None,
    )

    source = tmp_path / "raw" / "sources" / "doc.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("hello world", encoding="utf-8")

    from src.pipeline.collector import collect
    from src.types import SourceType

    async def drive():
        return await collect(
            task_id="kb-test123",
            source=str(source),
            source_type=SourceType.FILE,
        )

    payload = asyncio.run(drive())

    # raw_path should be the source path itself, NOT a staging copy.
    assert payload.raw_path == str(source), (
        f"collector raw_path should be the source itself; got {payload.raw_path!r}. "
        "After cleanup, no Inbox/Processing/<task_id>.md copy should exist."
    )

    # No inbox subdir should have been created under tmp_path
    inbox_dirs = list(tmp_path.glob("**/Inbox"))
    assert not inbox_dirs, (
        f"collector created Inbox/ subdirs: {inbox_dirs}. "
        "The 2026-07 cleanup should remove all Inbox-staged-copy code."
    )
