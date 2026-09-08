"""Tests for src.kc.views.book.wiki.preflight (Task 0).

Covers:
- Fail-closed preflight (uninit project, missing eligible dirs, output
  containment, schema mismatch, missing provider/model when use_llm,
  unauthorized --polish).
- Run lock: live contention, stale-takeover (age-expired-but-alive /
  dead-but-young), release on exception.
- Valid initialized project passes preflight + lock acquire.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bootstrap_project(tmp_path: Path) -> Path:
    """Create a minimal initialized project tree at tmp_path.

    Creates .llm-wiki/project.json with schema_version=v2.0 plus the
    three eligible input directories (concepts/, entities/, synthesis/).
    Returns the project root.
    """
    from src.wiki.storage.ensure import ensure_knowledge_base

    ensure_knowledge_base(tmp_path)

    project_json = tmp_path / ".llm-wiki" / "project.json"
    project_json.write_text(
        json.dumps(
            {
                "id": "test-uuid",
                "name": tmp_path.name,
                "created_at": 1700000000000,
                "schema_version": "v2.0",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return tmp_path


def _write_lock(
    path: Path,
    *,
    pid: int,
    started_at_ms: int,
    owner_token: str = "test-owner",
) -> None:
    """Write a synthetic lock file (without acquiring)."""
    payload = {
        "owner_token": owner_token,
        "pid": pid,
        "started_at": started_at_ms,
        "stale_after_seconds": 3600,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


# ---------------------------------------------------------------------------
# run_preflight
# ---------------------------------------------------------------------------


class TestRunPreflight:
    def test_uninitialized_project_fails_closed(self, tmp_path: Path) -> None:
        """No .llm-wiki/project.json → preflight fails closed without scanning."""
        from src.kc.views.book.wiki.preflight import (
            PreflightReport,
            run_preflight,
        )

        # tmp_path has no .llm-wiki/, no wiki/ — uninitialized.
        report = run_preflight(
            str(tmp_path),
            output_dir=tmp_path / "book-wiki",
            use_llm=False,
            provider_name=None,
            polish=False,
        )

        assert isinstance(report, PreflightReport)
        assert report.errors, "uninitialized project must produce errors"
        assert any("project" in err.message.lower() for err in report.errors)
        assert report.eligible_page_count == 0

    def test_missing_eligible_input_directories_fails(self, tmp_path: Path) -> None:
        """Initialized project but wiki/concepts/, entities/, synthesis/ absent."""
        from src.kc.views.book.wiki.preflight import run_preflight

        _bootstrap_project(tmp_path)
        # ensure_knowledge_base created the dirs — delete them so preflight must fail.
        for sub in ("concepts", "entities", "synthesis"):
            d = tmp_path / "wiki" / sub
            if d.exists():
                for child in d.iterdir():
                    child.unlink()
                d.rmdir()

        report = run_preflight(
            str(tmp_path),
            output_dir=tmp_path / "book-wiki",
            use_llm=False,
            provider_name=None,
            polish=False,
        )

        assert report.errors, "missing eligible dirs must produce errors"
        assert any(
            "concepts" in err.message.lower()
            or "entities" in err.message.lower()
            or "synthesis" in err.message.lower()
            for err in report.errors
        )

    def test_output_outside_project_root_rejected(self, tmp_path: Path) -> None:
        """output_dir must resolve inside project_root."""
        from src.kc.views.book.wiki.preflight import run_preflight

        _bootstrap_project(tmp_path)
        outside = tmp_path.parent / f"outside-{tmp_path.name}"

        report = run_preflight(
            str(tmp_path),
            output_dir=outside,
            use_llm=False,
            provider_name=None,
            polish=False,
        )

        assert report.errors
        assert any("outside" in err.message.lower() or "contain" in err.message.lower()
                   for err in report.errors)

    def test_output_inside_wiki_rejected(self, tmp_path: Path) -> None:
        """output_dir inside wiki/ must be rejected (wiki/ is source-of-truth)."""
        from src.kc.views.book.wiki.preflight import run_preflight

        _bootstrap_project(tmp_path)
        bad_output = tmp_path / "wiki" / "book-wiki"

        report = run_preflight(
            str(tmp_path),
            output_dir=bad_output,
            use_llm=False,
            provider_name=None,
            polish=False,
        )

        assert report.errors
        assert any("wiki" in err.message.lower() for err in report.errors)

    def test_output_inside_git_rejected(self, tmp_path: Path) -> None:
        """output_dir inside .git/ must be rejected."""
        from src.kc.views.book.wiki.preflight import run_preflight

        _bootstrap_project(tmp_path)
        (tmp_path / ".git").mkdir()
        bad_output = tmp_path / ".git" / "book-wiki"

        report = run_preflight(
            str(tmp_path),
            output_dir=bad_output,
            use_llm=False,
            provider_name=None,
            polish=False,
        )

        assert report.errors
        assert any(".git" in err.message.lower() for err in report.errors)

    def test_output_inside_book_wiki_dir_rejected(self, tmp_path: Path) -> None:
        """output_dir inside book-wiki/ must be rejected (avoid recursion)."""
        from src.kc.views.book.wiki.preflight import run_preflight

        _bootstrap_project(tmp_path)
        (tmp_path / "book-wiki").mkdir()
        bad_output = tmp_path / "book-wiki" / "sub"

        report = run_preflight(
            str(tmp_path),
            output_dir=bad_output,
            use_llm=False,
            provider_name=None,
            polish=False,
        )

        assert report.errors
        assert any("book-wiki" in err.message.lower() for err in report.errors)

    def test_output_inside_index_dir_rejected(self, tmp_path: Path) -> None:
        """output_dir inside .index/ must be rejected (operational data dir)."""
        from src.kc.views.book.wiki.preflight import run_preflight

        _bootstrap_project(tmp_path)
        bad_output = tmp_path / ".index" / "book-wiki"

        report = run_preflight(
            str(tmp_path),
            output_dir=bad_output,
            use_llm=False,
            provider_name=None,
            polish=False,
        )

        assert report.errors
        assert any(".index" in err.message.lower() for err in report.errors)

    def test_schema_version_mismatch_rejected(self, tmp_path: Path) -> None:
        """project.json schema_version differs from expected → fail."""
        from src.kc.views.book.wiki.preflight import run_preflight

        _bootstrap_project(tmp_path)
        # Overwrite schema_version with an incompatible value.
        project_json = tmp_path / ".llm-wiki" / "project.json"
        data = json.loads(project_json.read_text(encoding="utf-8"))
        data["schema_version"] = "v999.0"
        project_json.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        report = run_preflight(
            str(tmp_path),
            output_dir=tmp_path / "book-wiki",
            use_llm=False,
            provider_name=None,
            polish=False,
        )

        assert report.errors
        assert any(
            "schema" in err.message.lower() or "version" in err.message.lower()
            for err in report.errors
        )

    def test_use_llm_requires_provider_name(self, tmp_path: Path) -> None:
        """use_llm=True but provider_name=None → fail."""
        from src.kc.views.book.wiki.preflight import run_preflight

        _bootstrap_project(tmp_path)

        report = run_preflight(
            str(tmp_path),
            output_dir=tmp_path / "book-wiki",
            use_llm=True,
            provider_name=None,
            polish=False,
        )

        assert report.errors
        assert any("provider" in err.message.lower() for err in report.errors)

    def test_use_llm_with_unknown_provider_fails(self, tmp_path: Path) -> None:
        """use_llm=True with a provider name not in the registry → fail."""
        from src.kc.views.book.wiki.preflight import run_preflight

        _bootstrap_project(tmp_path)

        report = run_preflight(
            str(tmp_path),
            output_dir=tmp_path / "book-wiki",
            use_llm=True,
            provider_name="nonexistent-provider-xyz",
            polish=False,
        )

        assert report.errors
        assert any("provider" in err.message.lower() for err in report.errors)

    def test_use_llm_false_does_not_require_provider(self, tmp_path: Path) -> None:
        """use_llm=False (default) does NOT need provider/model/tokenizer."""
        from src.kc.views.book.wiki.preflight import run_preflight

        _bootstrap_project(tmp_path)

        report = run_preflight(
            str(tmp_path),
            output_dir=tmp_path / "book-wiki",
            use_llm=False,
            provider_name=None,
            polish=False,
        )

        # Pure-rule path must pass; no provider required.
        assert not report.errors, (
            f"pure-rule path must not require provider; got: {report.errors}"
        )
        assert report.provider is None
        assert report.model is None
        assert report.tokenizer is None

    def test_polish_without_content_export_authorization_fails(
        self, tmp_path: Path
    ) -> None:
        """polish=True but .llm-wiki/policy.json lacks content_export_authorized → fail."""
        from src.kc.views.book.wiki.preflight import run_preflight

        _bootstrap_project(tmp_path)
        # No policy.json → no authorization.
        policy = tmp_path / ".llm-wiki" / "policy.json"
        if policy.exists():
            policy.unlink()

        report = run_preflight(
            str(tmp_path),
            output_dir=tmp_path / "book-wiki",
            use_llm=True,
            provider_name="openai",  # provider must resolve for use_llm=True
            polish=True,
        )

        assert report.errors
        assert any(
            "polish" in err.message.lower()
            or "content_export" in err.message.lower()
            or "authorization" in err.message.lower()
            for err in report.errors
        )

    def test_polish_with_authorization_passes(self, tmp_path: Path) -> None:
        """polish=True with policy.json content_export_authorized=true → no polish error."""
        from src.kc.views.book.wiki.preflight import run_preflight

        _bootstrap_project(tmp_path)
        (tmp_path / ".llm-wiki" / "policy.json").write_text(
            json.dumps({"content_export_authorized": True, "external_llm_allowed": True}, ensure_ascii=False),
            encoding="utf-8",
        )

        report = run_preflight(
            str(tmp_path),
            output_dir=tmp_path / "book-wiki",
            use_llm=True,
            provider_name="openai",
            polish=True,
        )

        # Polish auth error must NOT appear. Other errors (e.g. use_llm
        # might still surface if provider resolution fails) are acceptable
        # in this test — we only assert the polish check passes.
        assert all(
            "polish" not in err.message.lower()
            and "content_export" not in err.message.lower()
            for err in report.errors
        )

    def test_valid_initialized_project_passes(self, tmp_path: Path) -> None:
        """Fully initialized project → preflight passes."""
        from src.kc.views.book.wiki.preflight import (
            PreflightReport,
            run_preflight,
        )

        _bootstrap_project(tmp_path)

        report = run_preflight(
            str(tmp_path),
            output_dir=tmp_path / "book-wiki",
            use_llm=False,
            provider_name=None,
            polish=False,
        )

        assert isinstance(report, PreflightReport)
        assert report.errors == ()
        assert report.project_root
        assert report.output_dir
        assert report.staging_root
        assert report.eligible_page_count == 0  # no actual pages written in bootstrap


# ---------------------------------------------------------------------------
# Run lock
# ---------------------------------------------------------------------------


class TestRunLock:
    def test_lock_acquire_and_release(self, tmp_path: Path) -> None:
        """acquire creates lock, release removes it."""
        from src.kc.views.book.wiki.preflight import (
            acquire_run_lock,
            release_run_lock,
        )

        lock_path = tmp_path / "run.lock"

        lock = acquire_run_lock(lock_path, stale_after_seconds=3600)
        assert lock_path.exists()
        assert lock.path == str(lock_path)
        assert lock.owner_token
        assert lock.pid == os.getpid()
        assert lock.stale_after_seconds == 3600

        release_run_lock(lock)
        assert not lock_path.exists()

    def test_lock_contention_blocks_second_acquire(self, tmp_path: Path) -> None:
        """Live lock → second acquire raises."""
        from src.kc.views.book.wiki.preflight import (
            LockBusyError,
            acquire_run_lock,
            release_run_lock,
        )

        lock_path = tmp_path / "run.lock"
        first = acquire_run_lock(lock_path, stale_after_seconds=3600)
        try:
            with pytest.raises(LockBusyError):
                acquire_run_lock(lock_path, stale_after_seconds=3600)
        finally:
            release_run_lock(first)

        # After release, a fresh acquire succeeds.
        second = acquire_run_lock(lock_path, stale_after_seconds=3600)
        release_run_lock(second)

    def test_stale_takeover_age_expired_but_alive_rejected(
        self, tmp_path: Path
    ) -> None:
        """Age > stale_after_seconds AND PID alive → reject (no auto-takeover)."""
        from src.kc.views.book.wiki.preflight import (
            LockBusyError,
            acquire_run_lock,
            release_run_lock,
        )

        lock_path = tmp_path / "run.lock"
        # Write a "live but old" lock owned by current PID (still alive).
        old_started_at_ms = int((time.time() - 7200) * 1000)  # 2 hours ago
        _write_lock(
            lock_path,
            pid=os.getpid(),  # alive
            started_at_ms=old_started_at_ms,
        )

        with pytest.raises(LockBusyError):
            acquire_run_lock(lock_path, stale_after_seconds=3600)

        # Lock still present (not taken over).
        assert lock_path.exists()
        # Cleanup via release on the synthetic lock — we synthesised it so
        # there's no RunLock handle; unlink directly to keep test tidy.
        lock_path.unlink(missing_ok=True)

    def test_stale_takeover_dead_but_young_rejected(self, tmp_path: Path) -> None:
        """PID dead AND age <= stale_after_seconds → reject (both conditions required)."""
        from src.kc.views.book.wiki.preflight import (
            LockBusyError,
            acquire_run_lock,
        )

        lock_path = tmp_path / "run.lock"
        # PID that cannot exist on this platform — pick a clearly-dead PID.
        # Use the well-known unused PID range; on Linux/Windows these never
        # correspond to a live process.
        dead_pid = 0x7FFFFFFE
        # Confirm the PID is not alive (defensive).
        # Just write the lock — if PID happens to be alive in some CI
        # environment, the test will still behave correctly because the
        # "young" condition should block takeover.
        recent_started_at_ms = int(time.time() * 1000)
        _write_lock(
            lock_path,
            pid=dead_pid,
            started_at_ms=recent_started_at_ms,
        )

        with pytest.raises(LockBusyError):
            acquire_run_lock(lock_path, stale_after_seconds=3600)

        # Lock still present (young + dead → no takeover).
        assert lock_path.exists()
        lock_path.unlink(missing_ok=True)

    def test_stale_takeover_old_and_dead_allowed(self, tmp_path: Path) -> None:
        """Age > stale_after_seconds AND PID dead → takeover succeeds."""
        from src.kc.views.book.wiki.preflight import (
            acquire_run_lock,
            release_run_lock,
        )

        lock_path = tmp_path / "run.lock"
        dead_pid = 0x7FFFFFFE
        old_started_at_ms = int((time.time() - 7200) * 1000)
        _write_lock(
            lock_path,
            pid=dead_pid,
            started_at_ms=old_started_at_ms,
        )

        lock = acquire_run_lock(lock_path, stale_after_seconds=3600)
        try:
            assert lock.pid == os.getpid()
            assert lock.owner_token
        finally:
            release_run_lock(lock)
        assert not lock_path.exists()

    def test_lock_released_on_exception_via_try_finally(
        self, tmp_path: Path
    ) -> None:
        """The plan requires callers to use try/finally; preflight surfaces a
        ``acquire_run_lock`` context-manager helper as a convenience. Verify
        the context-manager variant releases the lock even when the wrapped
        block raises."""
        from src.kc.views.book.wiki.preflight import acquire_run_lock

        lock_path = tmp_path / "run.lock"

        with pytest.raises(RuntimeError, match="boom"):
            with acquire_run_lock(lock_path, stale_after_seconds=3600):
                assert lock_path.exists()
                raise RuntimeError("boom")

        # Lock must be released even though we raised.
        assert not lock_path.exists()

    def test_lock_release_is_idempotent(self, tmp_path: Path) -> None:
        """release_run_lock called twice must not raise."""
        from src.kc.views.book.wiki.preflight import (
            acquire_run_lock,
            release_run_lock,
        )

        lock_path = tmp_path / "run.lock"
        lock = acquire_run_lock(lock_path, stale_after_seconds=3600)
        release_run_lock(lock)
        # Second call: lock file already gone, must not raise.
        release_run_lock(lock)


# ---------------------------------------------------------------------------
# Dataclass contracts
# ---------------------------------------------------------------------------


class TestDataclasses:
    def test_run_lock_is_frozen(self) -> None:
        """RunLock is a frozen dataclass."""
        from src.kc.views.book.wiki.preflight import RunLock

        lock = RunLock(
            path="/tmp/foo.lock",
            owner_token="tok",
            pid=1,
            started_at=0,
            stale_after_seconds=3600,
        )
        with pytest.raises(FrozenInstanceError):
            lock.pid = 2  # type: ignore[misc]

    def test_validation_error_is_frozen(self) -> None:
        """ValidationError is a frozen dataclass."""
        from src.kc.views.book.wiki.preflight import ValidationError

        err = ValidationError(
            code="E_X",
            stage="preflight",
            message="boom",
            context={},
        )
        with pytest.raises(FrozenInstanceError):
            err.code = "E_Y"  # type: ignore[misc]

    def test_preflight_report_fields(self) -> None:
        """PreflightReport exposes the documented fields."""
        from src.kc.views.book.wiki.preflight import PreflightReport

        report = PreflightReport(
            project_root="/abs/proj",
            output_dir="/abs/proj/book-wiki",
            staging_root="/abs/proj/.index/book-wiki/versions",
            provider=None,
            model=None,
            tokenizer=None,
            eligible_page_count=0,
            errors=(),
        )
        assert report.project_root == "/abs/proj"
        assert report.errors == ()
        with pytest.raises(FrozenInstanceError):
            report.eligible_page_count = 1  # type: ignore[misc]
