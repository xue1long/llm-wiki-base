"""hybrid_search must classify the semantic-retrieval failure (not silently swallow).

Background: previously the ``except Exception`` block in
``src.searcher.hybrid_search.hybrid_search`` (lines 119-124) silently
``pass``-ed. When the embedding provider misbehaved, the vector store
was down, or the provider returned an unexpected shape, operators
had no signal in the logs — search appeared to "work" (keyword
fallback succeeded) but the semantic failure mode was invisible.

The fix: log the exception class name plus a brief reason (truncated
to 200 chars) at WARNING level. The keyword-only fallback still runs
— operators see the failure mode AND search still returns results.
"""
import pytest

from src.llm.embedding_runtime import (
    set_embedding_provider,
    __reset_for_testing,
)
from src.searcher.hybrid_search import hybrid_search


class _BoomEmbedProvider:
    """Embedding provider that raises on every ``embed()`` call."""

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    def embed(self, texts: list[str]):  # noqa: ANN001 — signature mirrors runtime
        raise self._exc


def setup_function(_):
    __reset_for_testing()


def test_setup_resets_runtime_provider():
    """Sanity: setup_function cleared the runtime so we start each test clean."""
    from src.llm.embedding_runtime import get_embedding_provider

    with pytest.raises(RuntimeError):
        get_embedding_provider()


@pytest.mark.asyncio
async def test_semantic_exception_is_logged_with_class_and_reason(tmp_path, monkeypatch, caplog):
    """When the embedding provider raises, the warning must include the
    exception class name AND a snippet of the exception message — and the
    keyword fallback must actually run and return its results (proves
    degradation path is wired, not just an empty list)."""
    # Pre-populate a known keyword result so we can prove the keyword
    # fallback ran — not just that the function returned a list.
    knowledge_dir = tmp_path / "Knowledge"
    knowledge_dir.mkdir()
    kw_file = knowledge_dir / "kw-result.md"
    kw_file.write_text("python tutorials are great", encoding="utf-8")

    monkeypatch.chdir(tmp_path)  # keyword fallback looks at CWD/ so isolate it

    exc = RuntimeError("upstream embedding service returned 503")
    set_embedding_provider(_BoomEmbedProvider(exc))

    with caplog.at_level("WARNING", logger="src.searcher.hybrid_search"):
        result = await hybrid_search("python tutorials", top_k=5)

    # Warning was emitted
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert warnings, "expected at least one WARNING log record on semantic failure"

    msg = warnings[0].message
    # Class name present
    assert "RuntimeError" in msg, (
        f"exception class name must be in log message; got: {msg!r}"
    )
    # Reason snippet present (truncated to 200 chars max)
    assert "503" in msg or "upstream" in msg, (
        f"exception reason snippet must be in log message; got: {msg!r}"
    )
    # Mentions the keyword fallback path
    assert "keyword" in msg.lower(), (
        f"log message should mention keyword-only fallback; got: {msg!r}"
    )

    # Keyword fallback actually ran AND returned our pre-populated result.
    # This proves the function executed _keyword_search (not just ``return []``
    # after swallowing the semantic exception). Compare by filename since
    # ``_keyword_search`` returns paths relative to CWD (it uses
    # ``Path("Knowledge").rglob("*.md")``).
    paths = [r["path"] for r in result]
    assert "kw-result.md" in paths[0], (
        f"keyword fallback must return the pre-populated result; "
        f"got paths: {paths!r}"
    )


@pytest.mark.asyncio
async def test_semantic_exception_does_not_raise_to_caller(tmp_path, monkeypatch):
    """The exception must NOT propagate — search degradation is graceful."""
    monkeypatch.chdir(tmp_path)
    set_embedding_provider(_BoomEmbedProvider(ValueError("embed call timed out")))

    # Should not raise
    result = await hybrid_search("any query", top_k=5)
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_semantic_exception_message_is_truncated(tmp_path, monkeypatch, caplog):
    """Exception message must be truncated at the 200-char boundary, preserving
    the first 200 chars and dropping the rest (proves truncation, not deletion)."""
    monkeypatch.chdir(tmp_path)
    big_msg = "X" * 1000
    set_embedding_provider(_BoomEmbedProvider(RuntimeError(big_msg)))

    with caplog.at_level("WARNING", logger="src.searcher.hybrid_search"):
        await hybrid_search("query", top_k=5)

    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert warnings
    msg = warnings[0].message
    # The full 1000-char payload must NOT appear in the log
    assert big_msg not in msg, "exception message must be truncated before logging"
    # The reason argument (passed via %s after the class name) must be
    # truncated to at most 200 chars — production uses ``str(e)[:200]``.
    # Log records from ``logger.warning("...%s: %s...", cls, reason)`` carry
    # both args in ``record.args``. Find the reason arg (the 1000-char string,
    # possibly truncated) and assert its length.
    reason_arg = None
    for arg in warnings[0].args:
        if isinstance(arg, str) and arg.startswith("X"):
            reason_arg = arg
            break
    assert reason_arg is not None, (
        f"expected the exception reason argument in log args; got args={warnings[0].args!r}"
    )
    assert len(reason_arg) <= 200, (
        f"reason argument must be truncated to <= 200 chars; "
        f"got length={len(reason_arg)}"
    )
    # First 200 chars must be preserved (proves truncation, not deletion)
    assert reason_arg == "X" * 200, (
        f"expected first 200 chars preserved as 'X'*200; got: {reason_arg[:50]!r}..."
    )


def test_module_uses_module_logger_not_root():
    """The ``log`` / ``logger`` symbol in hybrid_search must be a module-level
    logger (so caplog can target it)."""
    # Re-import the module directly (the ``src.searcher`` package re-exports
    # the function ``hybrid_search`` under the same name, which shadows the
    # module reference).
    import importlib
    hs_real_module = importlib.import_module("src.searcher.hybrid_search")
    # hybrid_search uses ``logger`` (historical name); accept either.
    log_obj = getattr(hs_real_module, "logger", None) or getattr(hs_real_module, "log", None)
    assert log_obj is not None, (
        "hybrid_search module must expose a module-level logger "
        "(named 'logger' or 'log')"
    )
    assert log_obj.name == "src.searcher.hybrid_search", (
        f"logger must be named after the module; got: {log_obj.name!r}"
    )
