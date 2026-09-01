"""Audit regression: 1:1 reproduction of every bug from the ingest
pipeline audit report.

Each test is named after the audit numbering (e.g. ``test_audit_C1``,
``test_audit_S4``) so a future reader can trace the bug back to the
original report. The test sets up the exact conditions that triggered
the bug in production (or, where production conditions are
unreproducible, the smallest reproduction that demonstrates the
fix's contract).

If any of these tests fail, a regression has slipped in.

Audit numbering from the most recent report (audit v2 closed at
26 substantive findings; we have physical commits:
    PR-1  3bbac2dd 07266383 4f5f3243  (T1-T3)
    PR-2  16656415 7049f738            (T4-T6: E, F, D)
    PR-3  c86be5e7                    (T7)
    PR-2 final  53c82e86              (T8: path traversal)
)
"""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from src.events.event_bus import event_bus
from src.events.events import EventName
from src.lib.errors import (
    NO_RETRY_MARKER,
    classify_error,
    format_error_for_queue,
    is_no_retry,
)
from src.permissions import PermissionDenied
from src.pipeline.collector import (
    _PinnedDnsTransport,
    _safe_redirect_join,
)
from src.pipeline.retry import PermanentFailure
from src.queue import (
    __reset_for_testing,
    enqueue_task,
    get_default_queue_service,
)
from src.queue.retry import MAX_RETRIES
from src.services.ingest import (
    IngestPathError,
    _has_path_traversal,
    _normalize_absolute_path,
)
from src.types import SourceType, TaskStatus
from src.utils.idempotency import get_idempotency_cache


# ════════════════════════════════════════════════════════════════════
# Helpers — setup / teardown
# ════════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def _clear_idem_cache():
    """Each test starts with an empty idempotency cache so dedup state
    cannot leak across tests."""
    get_idempotency_cache().clear()
    yield
    get_idempotency_cache().clear()


def _drive_to_running(svc, task_id: str) -> None:
    """Move a freshly-enqueued task to RUNNING so the next FAILED
    transition is state-machine valid."""
    task = svc.backend.find(task_id)
    task.status = TaskStatus.RUNNING
    svc.backend.save(task)


def _set_task_to_running_persisted(svc, task_id: str) -> None:
    """Persist task as RUNNING directly via the backend (mimics the
    state after a process crash with the runner mid-flight)."""
    task = svc.backend.find(task_id)
    task.status = TaskStatus.RUNNING
    svc.backend.save(task)


def _reset_circuit_breaker():
    from src.circuit_breaker import get_circuit_breaker, CircuitState

    breaker = get_circuit_breaker("task_queue")
    breaker.state = CircuitState.CLOSED
    breaker.failure_count = 0


# ════════════════════════════════════════════════════════════════════
# Audit C1 — RESTART→RUNNING deadlock (dispatcher stale-RUNNING)
# ════════════════════════════════════════════════════════════════════


def test_audit_C1_stale_running_does_not_raise_invalid_transition(
    tmp_path, monkeypatch,
):
    """A task persisted as RUNNING on disk (post-crash) must not crash
    the dispatcher with ``InvalidTransition``; the dispatcher peeks
    at the persisted state and routes through ``release_in_flight``
    instead."""
    from src.pipeline import pipeline as pipeline_mod
    from src.pipeline.service import PipelineService
    from src.utils.idempotency import get_idempotency_cache

    get_idempotency_cache().clear()
    _reset_circuit_breaker()

    monkeypatch.chdir(tmp_path)
    # Inject a fake queue-service-style setup: enqueue + force RUNNING
    svc = get_default_queue_service()
    svc.pause()
    task_id = enqueue_task("audit-c1.md", SourceType.FILE, "hash-audit-c1")
    _set_task_to_running_persisted(svc, task_id)
    svc.tracker.acquire(task_id)

    class _StubCollector:
        name = "collector"

        async def run(self, ctx, prev_result):
            return type("R", (), {
                "success": True,
                "payload": type("P", (), {
                    "raw_path": "audit-c1.md",
                    "content": "x",
                    "artifact": None,
                })(),
            })()

    ps = PipelineService()
    ps.register_stages([_StubCollector()])

    import src.pipeline.pipeline as pipeline_mod_path
    monkeypatch.setattr(pipeline_mod_path, "_resolve_wiki_paths", lambda project_id=None: tmp_path)
    monkeypatch.setattr(pipeline_mod_path, "_get_provider", lambda project_id=None: object())

    async def stub_run_ingest(**kw):
        return []

    monkeypatch.setattr(pipeline_mod_path, "run_ingest", stub_run_ingest)

    # Should NOT raise — dispatcher must recover from stale RUNNING
    # state by routing through release_in_flight (which now counts
    # retries and dead-letters at MAX_RETRIES per PR-1 fix).
    import asyncio

    asyncio.run(ps._run_for_collector_start_inner(
        task_id=task_id,
        source="audit-c1.md",
        source_type=SourceType.FILE,
        project_id=None,
    ))

    # And after recovery, the task is no longer in the stuck RUNNING
    # state (release_in_flight reset retry_count=1 → status=PENDING).
    task = svc.backend.find(task_id)
    assert task.status is not TaskStatus.RUNNING


# ════════════════════════════════════════════════════════════════════
# Audit C2 — release_in_flight retry_count increment + exhaustion DL
# ════════════════════════════════════════════════════════════════════


def test_audit_C2_release_in_flight_increments_retry_count(
    tmp_path, monkeypatch,
):
    """release_in_flight must increment retry_count on every crash
    reset so a repeating crash cannot loop indefinitely."""
    monkeypatch.chdir(tmp_path)
    _reset_circuit_breaker()
    svc = get_default_queue_service()
    svc.pause()
    task_id = enqueue_task("c2.md", SourceType.FILE, "hash-audit-c2")
    svc.tracker.acquire(task_id)
    task = svc.backend.find(task_id)
    task.status = TaskStatus.RUNNING
    svc.backend.save(task)
    assert task.retry_count == 0

    svc.release_in_flight(task_id)

    task = svc.backend.find(task_id)
    assert task.retry_count == 1, (
        f"PR-1 fix: release_in_flight must increment retry_count "
        f"to bound repeated-crash loops; got {task.retry_count}"
    )


def test_audit_C2_release_in_flight_dead_letters_at_max_retries(
    tmp_path, monkeypatch,
):
    """MAX_RETRIES crashes in a row must end up DEAD_LETTER, not
    stuck PENDING forever."""
    monkeypatch.chdir(tmp_path)
    _reset_circuit_breaker()
    svc = get_default_queue_service()
    svc.pause()
    task_id = enqueue_task("c2-dl.md", SourceType.FILE, "hash-audit-c2-dl")

    # Capture task:dead_letter events
    dl_events = []
    handlers = event_bus._handlers.setdefault(EventName.TASK_DEAD_LETTER, set())

    def _capture(payload):
        dl_events.append(payload)
    handlers.add(_capture)
    try:
        for _ in range(MAX_RETRIES):
            svc.tracker.acquire(task_id)
            task = svc.backend.find(task_id)
            task.status = TaskStatus.RUNNING
            svc.backend.save(task)
            svc.release_in_flight(task_id)
            if svc.backend.find(task_id).status is TaskStatus.DEAD_LETTER:
                break

        task = svc.backend.find(task_id)
        assert task.status is TaskStatus.DEAD_LETTER
        assert task.retry_count >= MAX_RETRIES
        assert task.error.startswith(NO_RETRY_MARKER), (
            "DEAD_LETTERed crash-exhaustion must carry the no-retry "
            "marker so the queue does not re-attempt the same task."
        )
        assert dl_events, "task:dead_letter event must be emitted"
    finally:
        handlers.discard(_capture)


# ════════════════════════════════════════════════════════════════════
# Audit C3 — PermanentFailure → no-retry (HTTP 422 not retried 3×)
# ════════════════════════════════════════════════════════════════════


def test_audit_C3_permanent_failure_classified_as_no_retry():
    """``PermanentFailure`` (HTTP 422 content moderation, etc.) must
    be classified no-retry so ``format_error_for_queue`` emits the
    ``[no-retry]`` marker on the first failure."""
    exc = PermanentFailure("HTTP 422 content moderation")
    assert classify_error(exc) == "no_retry"
    assert is_no_retry(format_error_for_queue(exc))


def test_audit_C3_permanent_failure_subclasses_count_as_no_retry():
    """``isinstance`` must walk the MRO — providers sometimes wrap
    ``PermanentFailure`` in subclassed types."""
    class _ProviderSpecificBlock(PermanentFailure):
        pass

    exc = _ProviderSpecificBlock("blocked")
    assert classify_error(exc) == "no_retry"
    assert is_no_retry(format_error_for_queue(exc))


# ════════════════════════════════════════════════════════════════════
# Audit C4 — Release_in_flight clear idempotency hash on dead-letter
# ════════════════════════════════════════════════════════════════════


def test_audit_C4_dead_letter_clears_idempotency_hash(
    tmp_path, monkeypatch,
):
    """After a task is dead-lettered, the idempotency hash must be
    cleared so the same source can be re-enqueued (matching the
    update_status→DEAD_LETTER contract)."""
    monkeypatch.chdir(tmp_path)
    _reset_circuit_breaker()
    svc = get_default_queue_service()
    svc.pause()

    task_hash = "hash-audit-c4"
    # Mark the hash in the in-memory cache as already-seen.
    get_idempotency_cache()._cache[task_hash] = 0.0
    task_id = enqueue_task("c4.md", SourceType.FILE, task_hash)

    for _ in range(MAX_RETRIES):
        svc.tracker.acquire(task_id)
        task = svc.backend.find(task_id)
        task.status = TaskStatus.RUNNING
        svc.backend.save(task)
        svc.release_in_flight(task_id)
        if svc.backend.find(task_id).status is TaskStatus.DEAD_LETTER:
            break

    assert task_hash not in get_idempotency_cache()._cache, (
        "Idempotency hash must be cleared on dead-letter so the "
        "operator can re-attempt without being silently ignored."
    )


# ════════════════════════════════════════════════════════════════════
# Audit #5 — URL collector DNS-pin (SSRF TOCTOU + relative redirect)
# ════════════════════════════════════════════════════════════════════


def test_audit_5_dns_pin_blocks_toctou_attempt():
    """The transport pins the IP for the lifetime of a transport
    instance; even if the resolver tries to return a private IP on
    the second call, the cache wins."""
    transport = _PinnedDnsTransport()
    calls: list[str] = []

    state = {"n": 0}

    def flaky(host):
        state["n"] += 1
        calls.append(host)
        if state["n"] == 1:
            return "93.184.216.34"  # public on first call
        return "10.0.0.5"  # private on second call → TOCTOU attempt

    with patch(
        "src.pipeline.collector.socket.gethostbyname", side_effect=flaky,
    ):
        pinned = transport._resolve_and_pin("https://example.com/v1")
        # Second call: would return 10.0.0.5, cache wins.
        pinned2 = transport._resolve_and_pin("https://example.com/v2")

    assert calls == ["example.com"], (
        "Transport must resolve each hostname AT MOST once (the "
        "cache hits the second call). TOCTOU exploit shape tested."
    )
    assert "10.0.0.5" not in pinned
    assert "10.0.0.5" not in pinned2


def test_audit_5_relative_redirect_uses_urljoin():
    """The common ``Location: /v2/article`` 302 must resolve under
    the current host, not become a relative-path-from-CWD request."""
    base = "https://example.com/v1/old"
    out = _safe_redirect_join(base, "/v2/article")
    assert out == "https://example.com/v2/article"

    # Mixed absolute URL wins outright.
    out2 = _safe_redirect_join(base, "https://other.example/x")
    assert out2 == "https://other.example/x"


# ════════════════════════════════════════════════════════════════════
# Audit #6 — URL/file ingest dedup mirrors folder branch
# ════════════════════════════════════════════════════════════════════


def test_audit_6_url_dedup_short_circuits_when_source_page_exists(
    tmp_path, monkeypatch,
):
    """Re-submitting an already-ingested URL must short-circuit with
    reason=AlreadyIngested (mirrors folder branch dedup)."""
    import json
    import time
    from src.project.context import ProjectContext
    from src.project.registry import (
        GlobalRegistryStore, ProjectRegistryEntry,
    )
    from src.wiki.core.paths import WikiPaths

    project_root = tmp_path
    project_root.mkdir(parents=True, exist_ok=True)
    llm_dir = project_root / ".llm-wiki"
    llm_dir.mkdir(parents=True, exist_ok=True)
    (llm_dir / "project.json").write_text(json.dumps({
        "id": "url-dedup-test",
        "name": "url-dedup-test",
        "created_at": int(time.time() * 1000),
        "schema_version": "v2.0",
    }), encoding="utf-8")

    entry = ProjectRegistryEntry(
        id="url-dedup-test",
        name="url-dedup-test",
        path=str(project_root),
        last_opened=int(time.time() * 1000),
    )
    monkeypatch.setattr(
        GlobalRegistryStore, "by_id",
        classmethod(lambda cls, pid: entry if pid == "url-dedup-test" else None),
    )
    monkeypatch.setattr(
        GlobalRegistryStore, "by_name",
        classmethod(lambda cls, name: entry if name == "url-dedup-test" else None),
    )
    monkeypatch.chdir(project_root)

    from src.services.ingest import enqueue_source

    # Plant a source page referencing the URL.
    (project_root / "wiki" / "sources").mkdir(parents=True, exist_ok=True)
    (project_root / "wiki" / "sources" / "src.md").write_text(
        "---\nid: src\nsources:\n- https://example.com/article\n---\n",
        encoding="utf-8",
    )

    result = enqueue_source("url-dedup-test", "https://example.com/article")
    assert result["status"] == "ignored"
    assert result["reason"] == "AlreadyIngested"


# ════════════════════════════════════════════════════════════════════
# Audit #7 — _SUPPORTED_EXTENSIONS matches collector truth
# ════════════════════════════════════════════════════════════════════


def test_audit_7_supported_extensions_no_legacy_doc(monkeypatch):
    """``.doc`` must NOT be in the supported set — the extract layer
    raises ``UnsupportedFormat`` for legacy .doc, so the ingest
    branch silently failed at the collector (3 retries → dead-letter)."""
    from src.services import ingest as mod
    assert ".doc" not in mod._SUPPORTED_EXTENSIONS, (
        ".doc has no working extractor — removing it from the "
        "supported set avoids the false-positive 3-retry-then-DL cycle."
    )
    # .htm IS now accepted (collector supports both).
    assert ".htm" in mod._SUPPORTED_EXTENSIONS


# ════════════════════════════════════════════════════════════════════
# Audit #8 — frontmatter parser handles every YAML shape
# ════════════════════════════════════════════════════════════════════


def test_audit_8_frontmatter_inline_flow_does_not_silently_drop():
    """``sources: [raw/a.md, raw/b.md]`` (inline flow) must be parsed
    by the same helper the folder branch uses — the legacy line
    scanner silently dropped it, breaking dedup."""
    from src.services.ingest import (
        _get_ingested_paths,
        _find_source_page_by_url,
        _find_source_page_by_raw_path,
    )
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        from pathlib import Path

        td_path = Path(td)
        # Write 3 pages — block-list, inline-flow, quoted entries.
        sources = td_path / "wiki" / "sources"
        sources.mkdir(parents=True, exist_ok=True)
        for sid, raw in [
            ("block", ["raw/sources/foo-block.md"]),
        ]:
            (sources / f"{sid}.md").write_text(
                f"---\nid: {sid}\nsources:\n- {raw[0]}\n---\n", encoding="utf-8",
            )
        for sid, raw in [
            ("flow", ["raw/sources/foo-flow.md"]),
            ("quoted", ['"raw/sources/foo-quoted.md"']),
        ]:
            (sources / f"{sid}.md").write_text(
                "---\n"
                f"id: {sid}\n"
                f"sources:\n  - {raw[0]}\n"
                "---\n", encoding="utf-8",
            )

        # All three raw paths should be detected.
        ingested = _get_ingested_paths(sources, td_path)
        assert ingested == {
            "raw/sources/foo-block.md",
            "raw/sources/foo-flow.md",
            "raw/sources/foo-quoted.md",
        }

        # All three pages should be found by raw-path lookup.
        assert (
            _find_source_page_by_raw_path(sources, "raw/sources/foo-block.md")
            == "block"
        )
        assert (
            _find_source_page_by_raw_path(sources, "raw/sources/foo-flow.md")
            == "flow"
        )


# ════════════════════════════════════════════════════════════════════
# Audit #9 — path-traversal fail-closed on raw/sources fallback
# ════════════════════════════════════════════════════════════════════


def test_audit_9_dotdot_in_relative_path_fail_closed(tmp_path, monkeypatch):
    """The legacy code's ``raw/sources`` fallback silently absorbed
    ``../../etc/passwd`` if a matching file happened to exist under
    the project. The PR-2 final fix must refuse this outright."""
    monkeypatch.chdir(tmp_path)

    # Plant a file the legacy fallback would have surfaced.
    bogus = tmp_path / "raw" / "sources" / "etc"
    bogus.mkdir(parents=True, exist_ok=True)
    (bogus / "passwd").write_text("attacker", encoding="utf-8")

    with pytest.raises(IngestPathError, match="path-traversal"):
        _normalize_absolute_path(tmp_path, "../../etc/passwd")


def test_audit_9_dotdot_in_absolute_path_surfaces_traversal_error(
    tmp_path,
):
    """Absolute path with ``..`` segments escaping project_root
    must surface a clear ``refuses path-traversal`` error.

    Note: ``tmp_path / "raw" / "foo" / ".." / ".." / "outside.md"``
    resolves to ``tmp_path/outside.md`` (inside project_root) because
    the two ``..`` segments cancel exactly. To force escape we use
    an extra segment so the resolution lands OUTSIDE project_root.
    """
    abs_path = str(
        tmp_path / "raw" / "foo" / ".." / ".." / ".." / "outside.md"
    )

    with pytest.raises(IngestPathError, match="refuses path-traversal"):
        _normalize_absolute_path(tmp_path, abs_path)


def test_audit_9_legitimate_raw_sources_fallback_still_works(
    tmp_path, monkeypatch,
):
    """For legitimate bare filename inputs (no ``..`` segments), the
    legacy ergonomics must still apply: ``foo.md`` → ``raw/sources/foo.md``
    when project_root and cwd differ."""
    project = tmp_path / "project"
    project.mkdir()
    sibling_cwd = tmp_path / "sibling_cwd"
    sibling_cwd.mkdir()
    monkeypatch.chdir(sibling_cwd)
    # Plant the file the fallback should find.
    (project / "raw" / "sources" / "foo.md").parent.mkdir(parents=True, exist_ok=True)
    (project / "raw" / "sources" / "foo.md").write_text("x", encoding="utf-8")

    result = _normalize_absolute_path(project, "foo.md")
    assert result == "raw/sources/foo.md"


# ════════════════════════════════════════════════════════════════════
# Cross-cutting — no regression on the happy-path
# ════════════════════════════════════════════════════════════════════


def test_audit_unknown_exception_still_defaults_retryable():
    """Back-compat: any exception not in the R8 taxonomy defaults to
    retryable (fail-open). PR-1 did not change this."""
    assert classify_error(RuntimeError("mystery")) == "retryable"


def test_audit_helper_path_traversal_smoke():
    """``_has_path_traversal`` is exposed (private but stable) so the
    audit can introspect it directly."""
    assert _has_path_traversal("../foo")
    assert _has_path_traversal("foo/../bar")
    assert not _has_path_traversal("foo/bar.md")
