"""Tests for I-pipeline-2 (partial fix in T8): cascade_delete opens its own
atomic_pipeline_op internally; callers no longer need to wrap it.

Before T8 the function relied on the caller wrapping it in atomic_pipeline_op
(which was inconsistent and easy to forget). T8 self-wraps it so the
delete-cascade always commits as one batch.
"""
import pytest

from src.wiki.core.types import PageType, WikiPage
from src.wiki.features.cascade_delete import cascade_delete
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.core.paths import WikiPaths
from src.wiki.storage.page_writer import write_page
from src.wiki.features.indexer import append_to_index
from src.lib.write_hooks import flush_pending_writes


def test_cascade_delete_self_wraps_in_atomic_context(tmp_path, monkeypatch):
    """Calling cascade_delete WITHOUT an outer AtomicContext must still
    defer deletions safely — when write_page fails mid-flight, no
    deletions leak to disk."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    write_page(p, WikiPage(id="src-1", title="Source", type=PageType.SOURCE, sources=["raw/sources/x.pdf"], body=""))
    write_page(p, WikiPage(id="ent-a", title="A", type=PageType.ENTITY, sources=["raw/sources/x.pdf", "raw/sources/y.pdf"], body="links"))

    def fail_write(*args, **kwargs):
        raise RuntimeError("mid-operation")

    monkeypatch.setattr("src.wiki.features.cascade_delete.write_page", fail_write)

    # No `with atomic_pipeline_op(p):` wrapper — cascade_delete opens its own.
    with pytest.raises(RuntimeError):
        cascade_delete(p, "src-1")

    # Source and entity files must still exist on disk; nothing leaked.
    assert (p.wiki_sources / "src-1.md").exists()
    assert (p.wiki_entities / "ent-a.md").exists()
    flush_pending_writes()


def test_cascade_delete_commits_atomically_without_caller_wrapper(tmp_path):
    """Happy path: cascade_delete called plainly (no caller AtomicContext)
    still commits all writes atomically."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    write_page(p, WikiPage(id="src-1", title="Source", type=PageType.SOURCE, sources=["raw/sources/x.pdf"], body=""))
    write_page(p, WikiPage(id="ent-a", title="A", type=PageType.ENTITY, sources=["raw/sources/x.pdf"], body="links"))
    write_page(p, WikiPage(id="ent-b", title="B", type=PageType.ENTITY, sources=["raw/sources/y.pdf"], body="also links"))
    append_to_index(p, [("src-1", PageType.SOURCE, "Source"), ("ent-a", PageType.ENTITY, "A"), ("ent-b", PageType.ENTITY, "B")])

    # Plain call, no outer atomic_pipeline_op.
    result = cascade_delete(p, "src-1")

    assert not (p.wiki_sources / "src-1.md").exists()
    assert not (p.wiki_entities / "ent-a.md").exists()
    assert (p.wiki_entities / "ent-b.md").exists()
    assert "src-1" not in p.llm_wiki_index.read_text(encoding="utf-8")
    assert result["deleted_source"] is True
    assert "ent-a" in result["deleted_pages"]


def test_cascade_delete_idempotent_under_nested_atomic_context(tmp_path):
    """If the caller ALSO wraps in atomic_pipeline_op, the nested context
    is a no-op (cascade_delete's own inner context is the outer one that
    actually flushes) — no duplicate flushes, no broken state."""
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    write_page(p, WikiPage(id="src-1", title="Source", type=PageType.SOURCE, sources=["raw/sources/x.pdf"], body=""))
    write_page(p, WikiPage(id="ent-a", title="A", type=PageType.ENTITY, sources=["raw/sources/x.pdf"], body="links"))

    from src.wiki.storage.atomic_ctx_helpers import atomic_pipeline_op
    with atomic_pipeline_op(p):
        result = cascade_delete(p, "src-1")

    assert result["deleted_source"] is True
    assert not (p.wiki_sources / "src-1.md").exists()
    assert not (p.wiki_entities / "ent-a.md").exists()


def test_cascade_atomic_op_is_first_line():
    """Regression (T8 auditfix Finding 2): cascade_delete must open its
    atomic_pipeline_op() context as the FIRST executable line of the
    function body. All setup, validation, and cascade work happens INSIDE
    the context — if any step raises, the atomic context's __exit__
    flushes nothing and the wiki is unchanged.

    Before the fix, ensure_knowledge_base, source-path construction, and
    the FileNotFoundError existence check ran BEFORE the context manager,
    which meant a failed existence check correctly raised (no state change),
    but if any future validation were added between ensure_kb and the
    context, partial state could already be committed.

    This test introspects the function source to verify the atomic context
    is the first executable statement.
    """
    import inspect
    from src.wiki.features.cascade_delete import cascade_delete

    source = inspect.getsource(cascade_delete)
    # Walk through the function body line-by-line and find the first
    # non-docstring, non-signature, non-blank executable statement.
    lines = source.split("\n")
    found_signature = False
    in_docstring = False
    docstring_quote = None
    first_executable = None
    for line in lines:
        stripped = line.strip()
        # Skip the `def` line itself.
        if not found_signature and stripped.startswith("def "):
            found_signature = True
            continue
        if not found_signature:
            continue
        # Skip blanks.
        if not stripped:
            continue
        # Handle multi-line docstrings: track open/close and skip them.
        if not in_docstring:
            if stripped.startswith('"""') or stripped.startswith("'''"):
                docstring_quote = stripped[:3]
                # Single-line docstring case.
                if stripped.count(docstring_quote) >= 2:
                    continue
                in_docstring = True
                continue
        else:
            if docstring_quote in stripped:
                in_docstring = False
                docstring_quote = None
            continue
        # Skip comments.
        if stripped.startswith("#"):
            continue
        first_executable = stripped
        break

    assert first_executable is not None, "could not locate first executable line"
    assert "atomic_pipeline_op" in first_executable, (
        f"first executable statement must open atomic_pipeline_op; got: "
        f"{first_executable!r}"
    )
    assert first_executable.startswith("with "), (
        f"first executable must be a `with atomic_pipeline_op(paths):` line; "
        f"got: {first_executable!r}"
    )


def test_cascade_atomic_op_validation_failure_commits_nothing(tmp_path, monkeypatch):
    """Regression (T8 auditfix Finding 2): if any setup or validation
    inside cascade_delete fails (after the atomic context has opened), no
    safe_write() calls should be committed to disk.

    Strategy: inject a fake atomic_pipeline_op context that tracks whether
    any safe_write was called WHILE inside the context. Force
    ensure_knowledge_base to raise and assert nothing was buffered.
    """
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    write_page(p, WikiPage(id="src-1", title="Source", type=PageType.SOURCE, sources=["raw/sources/x.pdf"], body=""))
    write_page(p, WikiPage(id="ent-a", title="A", type=PageType.ENTITY, sources=["raw/sources/x.pdf"], body="links"))

    # Track safe_write calls made while inside any atomic context.
    safe_write_calls_inside = []
    original_safe_write = __import__(
        "src.lib.write_hooks", fromlist=["safe_write"]
    ).safe_write

    def tracking_safe_write(path, content):
        from src.lib.atomic_ctx import is_suspended
        if is_suspended():
            safe_write_calls_inside.append((str(path), content))
        original_safe_write(path, content)

    monkeypatch.setattr(
        "src.wiki.features.cascade_delete.safe_write",
        tracking_safe_write,
    )

    # Force ensure_knowledge_base (called inside cascade_delete, after the
    # atomic context opens) to raise — this simulates any validation/setup
    # failure AFTER the context manager has opened.
    def fail_ensure(*args, **kwargs):
        raise RuntimeError("setup failed mid-flight")

    monkeypatch.setattr(
        "src.wiki.features.cascade_delete.ensure_knowledge_base",
        fail_ensure,
    )

    # Capture state BEFORE the call.
    src_existed_before = (p.wiki_sources / "src-1.md").exists()
    ent_existed_before = (p.wiki_entities / "ent-a.md").exists()

    with pytest.raises(RuntimeError, match="setup failed mid-flight"):
        cascade_delete(p, "src-1")

    # Critical assertion: no safe_write was called WHILE inside the
    # atomic context (because ensure_knowledge_base raised before any
    # safe_write had a chance to run).
    assert safe_write_calls_inside == [], (
        f"safe_write was called inside atomic context before setup "
        f"completed; calls: {safe_write_calls_inside!r}"
    )

    # The wiki state on disk must be unchanged (the atomic context
    # swallowed all writes — both the ones that would have been buffered
    # and the DELETE_SENTINEL ones).
    assert (p.wiki_sources / "src-1.md").exists() == src_existed_before
    assert (p.wiki_entities / "ent-a.md").exists() == ent_existed_before
