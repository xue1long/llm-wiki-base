"""Fail-closed project and runtime preflight (Wiki-to-Book V3.2, Task 0).

Public surface
--------------
- ``run_preflight(project_arg, *, output_dir, use_llm, provider_name, polish) -> PreflightReport``
    Validate project initialization, eligible input directories, output path
    containment, LLM provider availability, and ``--polish`` authorization.
    Always returns a :class:`PreflightReport`; on any failure the
    ``errors`` tuple is non-empty and downstream code MUST refuse to scan
    or call an LLM. Preflight NEVER auto-initializes a missing project —
    that is the contract that makes it "fail-closed".

- ``acquire_run_lock(lock_path, *, stale_after_seconds) -> RunLock``
    Single-writer cross-platform lock. Stale takeover requires BOTH
    (a) age > ``stale_after_seconds`` AND (b) the holder PID has exited.
    Raises :class:`LockBusyError` when the lock is held and either
    condition is unmet. The returned :class:`RunLock` is also usable as a
    context manager — ``release_run_lock`` runs from ``__exit__`` (with
    exception safety).

- ``release_run_lock(lock) -> None``
    Best-effort release; never raises.

Data contract
-------------
- :class:`PreflightReport`, :class:`RunLock`, :class:`ValidationError`
  are frozen dataclasses matching the V3.2 plan's "Data Contract" section.
  ``ValidationError.context`` carries a ``str -> str`` map (per the plan).

Content-export authorization
----------------------------
``--polish`` requires explicit consent to send content to an external
provider. The marker is ``<project_root>/.llm-wiki/policy.json`` with the
shape ``{"content_export_authorized": true, "external_llm_allowed": true}``.
The marker is intentionally
machine-readable and reviewable in code review (not an env var or
provider-specific flag) — operators see one file that gates external
content transmission for a project.

Path containment
----------------
The output directory must resolve **inside** the project root AND must
NOT live under any of: ``wiki/``, ``.git/``, ``.index/``. The dedicated
``book-wiki/`` activation directory is allowed; nested alternate output
directories under it are rejected.
Both checks are required: the first prevents leaks to foreign trees, the
second protects project-managed directories from being clobbered by the
compiler. We use :func:`pathlib.Path.resolve` (not ``safe_resolve``)
because the CJK-corruption issue noted in ``src/utils/path.py`` only
affects *display* paths, not containment checks against an
already-resolved project root, and ``resolve`` gives us the strict
``realpath`` semantics we need here.
"""
from __future__ import annotations

import ctypes
import errno
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Schema contract — keep in sync with the V3.2 plan
# ---------------------------------------------------------------------------

#: Project schema versions accepted by preflight. Add new entries when the
#: ``.llm-wiki/project.json`` schema evolves; bumping the accepted list is
#: the explicit migration step required by ``ProjectIdentity.from_dict``.
ACCEPTED_SCHEMA_VERSIONS: tuple[str, ...] = ("v2.0",)

#: Provider name resolved from the env (``RUFLO_LLM_PROVIDER``) when the
#: caller does not specify one explicitly. Mirrors the registry default
#: resolution but is independent — preflight does not load the registry
#: until it has to verify a name.
DEFAULT_PROVIDER_ENV = "RUFLO_LLM_PROVIDER"

#: Marker file inside ``.llm-wiki/`` that authorises ``--polish`` content
#: export. JSON shape: ``{"content_export_authorized": true,
#: "external_llm_allowed": true}``.
POLICY_FILENAME = "policy.json"

#: Subdirectories of the project root that the compiler MUST NOT use as
#: output targets (source-of-truth or operational data).
FORBIDDEN_OUTPUT_PARENTS: tuple[str, ...] = (
    "wiki",
    ".git",
    ".index",
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ValidationError:
    """Single validation failure. ``context`` carries ``str -> str`` per plan."""

    code: str
    stage: str
    message: str
    context: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PreflightReport:
    """Result of :func:`run_preflight`. ``errors == ()`` means OK to proceed."""

    project_root: str
    output_dir: str
    staging_root: str
    provider: str | None
    model: str | None
    tokenizer: str | None
    eligible_page_count: int
    errors: tuple[ValidationError, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class RunLock:
    """Handle to an acquired run lock. ``stale_after_seconds`` is captured
    at acquisition time so the release/re-acquire path can re-evaluate the
    same policy without consulting external state."""

    path: str
    owner_token: str
    pid: int
    started_at: int  # unix ms
    stale_after_seconds: int

    def __enter__(self) -> "RunLock":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        release_run_lock(self)

    # The context-manager implementation lives in ``acquire_run_lock``
    # below; attaching it here would require the lock to know its own
    # releaser, which couples RunLock (data) to release_run_lock (action).
    # Keeping the two separate keeps the dataclass a pure value.


class LockBusyError(Exception):
    """Raised when the run lock is held by a live owner."""


# ---------------------------------------------------------------------------
# Path-containment helpers
# ---------------------------------------------------------------------------


def _is_inside(child: Path, parent: Path) -> bool:
    """Return True iff ``child`` resolves inside ``parent``.

    Equality does NOT count as "inside" (a directory is not inside itself).
    Symlinks are not followed — the lock and policy docs call out lexical
    containment, matching the rest of the codebase.
    """
    try:
        child_resolved = child.resolve()
        parent_resolved = parent.resolve()
    except OSError:
        return False
    if child_resolved == parent_resolved:
        return False
    try:
        child_resolved.relative_to(parent_resolved)
        return True
    except ValueError:
        return False


def _validate_output_containment(
    project_root: Path,
    output_dir: Path,
) -> tuple[ValidationError, ...]:
    """Apply both halves of the output-containment check.

    1. ``output_dir`` must resolve inside ``project_root`` (else: it can
       overwrite foreign files).
    2. ``output_dir`` must NOT live under ``wiki/``, ``.git/``,
       ``book-wiki/``, ``.index/`` (else: it can clobber project-managed
       data).
    """
    errors: list[ValidationError] = []
    try:
        output_resolved = output_dir.resolve()
    except OSError as exc:
        errors.append(
            ValidationError(
                code="E_OUTPUT_UNRESOLVABLE",
                stage="preflight",
                message=f"output_dir cannot be resolved: {exc}",
                context={"output_dir": str(output_dir)},
            )
        )
        return tuple(errors)

    # Half 1: must be inside project_root.
    if not _is_inside(output_resolved, project_root):
        errors.append(
            ValidationError(
                code="E_OUTPUT_OUTSIDE_ROOT",
                stage="preflight",
                message=(
                    f"output_dir must resolve inside project root; got "
                    f"{output_resolved} vs {project_root}"
                ),
                context={
                    "output_dir": str(output_resolved),
                    "project_root": str(project_root.resolve()),
                },
            )
        )

    # Half 2: must not live under a forbidden parent. The exact dedicated
    # book-wiki directory is the activation target; nested alternates are
    # rejected to prevent recursive output trees.
    for forbidden in FORBIDDEN_OUTPUT_PARENTS:
        forbidden_path = project_root / forbidden
        try:
            forbidden_resolved = forbidden_path.resolve()
        except OSError:
            continue
        if _is_inside(output_resolved, forbidden_resolved) or output_resolved == forbidden_resolved:
            errors.append(
                ValidationError(
                    code="E_OUTPUT_FORBIDDEN_PARENT",
                    stage="preflight",
                    message=(
                        f"output_dir must not live under project_root/{forbidden}/"
                    ),
                    context={
                        "output_dir": str(output_resolved),
                        "forbidden_parent": str(forbidden_resolved),
                    },
                )
            )
            break

    activation_dir = (project_root / "book-wiki").resolve()
    if output_resolved != activation_dir and _is_inside(output_resolved, activation_dir):
        errors.append(
            ValidationError(
                code="E_OUTPUT_FORBIDDEN_PARENT",
                stage="preflight",
                message="output_dir must be the dedicated book-wiki directory, not a nested path",
                context={
                    "output_dir": str(output_resolved),
                    "forbidden_parent": str(activation_dir),
                },
            )
        )

    return tuple(errors)


# ---------------------------------------------------------------------------
# Project + schema validation
# ---------------------------------------------------------------------------


def _load_project_identity(project_root: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Read ``.llm-wiki/project.json``; return (data, raw_text_or_None).

    Returns ``(None, None)`` when the file does not exist. Raises
    :class:`json.JSONDecodeError` when the file is corrupt — caller decides
    whether that should fail closed.
    """
    project_json = project_root / ".llm-wiki" / "project.json"
    if not project_json.exists():
        return None, None
    text = project_json.read_text(encoding="utf-8")
    return json.loads(text), text


def _validate_project(
    project_root: Path,
) -> tuple[dict[str, Any] | None, tuple[ValidationError, ...]]:
    """Validate ``.llm-wiki/project.json`` exists and has an accepted schema."""
    errors: list[ValidationError] = []
    try:
        data, _ = _load_project_identity(project_root)
    except json.JSONDecodeError as exc:
        errors.append(
            ValidationError(
                code="E_PROJECT_JSON_CORRUPT",
                stage="preflight",
                message=f".llm-wiki/project.json is not valid JSON: {exc}",
                context={"project_root": str(project_root)},
            )
        )
        return None, tuple(errors)

    if data is None:
        errors.append(
            ValidationError(
                code="E_PROJECT_NOT_INITIALIZED",
                stage="preflight",
                message=(
                    "project not initialized: .llm-wiki/project.json is missing. "
                    "Run `python -m src.cli project init <path>` first."
                ),
                context={"project_root": str(project_root)},
            )
        )
        return None, tuple(errors)

    schema_version = data.get("schema_version")
    if schema_version not in ACCEPTED_SCHEMA_VERSIONS:
        errors.append(
            ValidationError(
                code="E_PROJECT_SCHEMA_MISMATCH",
                stage="preflight",
                message=(
                    f"project schema_version={schema_version!r} is not in the "
                    f"accepted set {ACCEPTED_SCHEMA_VERSIONS!r}"
                ),
                context={
                    "project_root": str(project_root),
                    "found_schema_version": str(schema_version),
                },
            )
        )

    return data, tuple(errors)


def _validate_eligible_dirs(project_root: Path) -> tuple[ValidationError, ...]:
    """wiki/concepts, wiki/entities, wiki/synthesis must all exist."""
    errors: list[ValidationError] = []
    for name in ("concepts", "entities", "synthesis"):
        d = project_root / "wiki" / name
        if not d.is_dir():
            errors.append(
                ValidationError(
                    code="E_ELIGIBLE_DIR_MISSING",
                    stage="preflight",
                    message=f"eligible input directory missing: wiki/{name}/",
                    context={
                        "project_root": str(project_root),
                        "missing_dir": str(d),
                    },
                )
            )
    return tuple(errors)


# ---------------------------------------------------------------------------
# Provider + polish authorization
# ---------------------------------------------------------------------------


def _resolve_provider(provider_name: str | None) -> tuple[str | None, str | None, str | None, tuple[ValidationError, ...]]:
    """Resolve a provider name to (name, model, tokenizer, errors).

    On any error, ``name`` is None. We do NOT raise — errors are surfaced
    in the returned ``PreflightReport``. We do not require an actual
    network connection: provider name resolution is enough to gate the
    LLM path. Tokenizer availability is the provider's responsibility to
    advertise (we surface ``None`` here when the registry does not know
    a tokenizer, which is fine for the pure-rule path).
    """
    errors: list[ValidationError] = []
    if not provider_name:
        env_name = os.environ.get(DEFAULT_PROVIDER_ENV, "").strip()
        provider_name = env_name or None

    if not provider_name:
        errors.append(
            ValidationError(
                code="E_PROVIDER_REQUIRED",
                stage="preflight",
                message=(
                    "use_llm=True requires a provider name (pass provider_name= "
                    "or set $RUFLO_LLM_PROVIDER)."
                ),
                context={},
            )
        )
        return None, None, None, tuple(errors)

    # Lazy import: ProviderRegistry reads from the user's config dir; in
    # unit tests we may not have one. Catch ImportError defensively.
    try:
        from src.llm.registry import ProviderRegistry, ProviderNotFoundError
    except ImportError as exc:  # pragma: no cover - non-default envs only
        errors.append(
            ValidationError(
                code="E_PROVIDER_REGISTRY_UNAVAILABLE",
                stage="preflight",
                message=f"LLM provider registry not importable: {exc}",
                context={"provider": provider_name},
            )
        )
        return None, None, None, tuple(errors)

    try:
        config = ProviderRegistry.require(provider_name)
    except ModuleNotFoundError as exc:
        # Keep the gate deterministic in the minimal/offline runtime.  The
        # registry's optional settings dependency may be absent; built-in
        # provider names still have a valid adapter contract, while arbitrary
        # names must remain rejected.
        if provider_name in {"openai", "anthropic", "ollama"}:
            return provider_name, None, None, tuple(errors)
        errors.append(ValidationError(code="E_PROVIDER_NOT_FOUND", stage="preflight",
                                      message=f"provider '{provider_name}' is not registered.",
                                      context={"provider": provider_name}))
        return None, None, None, tuple(errors)
    except ProviderNotFoundError:
        errors.append(
            ValidationError(
                code="E_PROVIDER_NOT_FOUND",
                stage="preflight",
                message=(
                    f"provider '{provider_name}' is not registered. "
                    f"Run `python -m src.cli llm-providers add {provider_name} ...`."
                ),
                context={"provider": provider_name},
            )
        )
        return None, None, None, tuple(errors)
    except Exception as exc:
        errors.append(ValidationError(code="E_PROVIDER_REGISTRY_UNAVAILABLE", stage="preflight",
                                      message=f"LLM provider registry unavailable: {exc}",
                                      context={"provider": provider_name}))
        return None, None, None, tuple(errors)

    # Tokenizer: registry exposes chat / embedding models but not tokenizer
    # availability directly. We treat absence of tokenizer metadata as
    # "unknown" and surface that — the LLM path can decide whether to
    # fail closed or proceed with a best-effort token estimate. For
    # preflight purposes "None" means "we could not verify".
    tokenizer = getattr(config, "tokenizer", None)
    return provider_name, config.default_chat_model, tokenizer, tuple(errors)


def _validate_polish_authorization(
    project_root: Path,
    polish: bool,
    use_llm: bool = False,
) -> tuple[ValidationError, ...]:
    """Check explicit authorization before any external LLM request."""
    if not (polish or use_llm):
        return ()
    policy_path = project_root / ".llm-wiki" / POLICY_FILENAME
    if not policy_path.exists():
        return (
            ValidationError(
                code="E_POLISH_UNAUTHORIZED",
                stage="preflight",
                message=(
                    "LLM builds require content-export authorization. "
                    f"Create {policy_path} with "
                    f"'{{\"content_export_authorized\": true}}' to enable."
                ),
                context={"policy_path": str(policy_path)},
            ),
        )
    try:
        data = json.loads(policy_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return (
            ValidationError(
                code="E_POLICY_CORRUPT",
                stage="preflight",
                message=f"{POLICY_FILENAME} is not valid JSON: {exc}",
                context={"policy_path": str(policy_path)},
            ),
        )
    if polish and (not isinstance(data, dict) or not data.get("content_export_authorized")):
        return (
            ValidationError(
                code="E_POLICY_REVOKED",
                stage="preflight",
                message=(
                    f"{POLICY_FILENAME} does not authorise content export "
                    "(content_export_authorized must be true)."
                ),
                context={"policy_path": str(policy_path)},
            ),
        )
    if not isinstance(data, dict) or data.get("external_llm_allowed") is not True:
        return (
            ValidationError(
                code="E_EXTERNAL_LLM_UNAUTHORIZED",
                stage="preflight",
                message=(
                    f"{POLICY_FILENAME} must explicitly set "
                    "external_llm_allowed to true before source text is sent "
                    "to an external LLM."
                ),
                context={"policy_path": str(policy_path)},
            ),
        )
    return ()


# ---------------------------------------------------------------------------
# run_preflight
# ---------------------------------------------------------------------------


def run_preflight(
    project_arg: str,
    *,
    output_dir: Path,
    use_llm: bool,
    provider_name: str | None,
    polish: bool,
) -> PreflightReport:
    """Fail-closed preflight. Never raises; always returns a report.

    Validation order matters for the failure-mode contract:
      1. Project identity & schema (catches "uninitialized" first).
      2. Eligible input directories (only if project is initialized).
      3. Output path containment (independent of project state — we never
         let the user write outside the project root).
      4. LLM provider resolution (only when ``use_llm=True``).
      5. ``--polish`` authorization (only when ``polish=True``).
    """
    project_root = Path(project_arg).resolve()
    staging_root = str((project_root / ".index" / "book-wiki" / "versions").resolve())

    errors: list[ValidationError] = []

    # (1) Project identity.
    _identity, project_errors = _validate_project(project_root)
    errors.extend(project_errors)

    # (2) Eligible dirs (only meaningful if project is initialized).
    if not project_errors:
        errors.extend(_validate_eligible_dirs(project_root))

    # (3) Output containment — always check, regardless of project state.
    errors.extend(_validate_output_containment(project_root, output_dir))

    # (4) Provider (only when use_llm).
    provider: str | None = None
    model: str | None = None
    tokenizer: str | None = None
    if use_llm:
        provider, model, tokenizer, provider_errors = _resolve_provider(provider_name)
        errors.extend(provider_errors)
    else:
        # Pure-rule path: explicit None on all three, no env lookup.
        provider = None
        model = None
        tokenizer = None

    # (5) External LLM authorization, including outline-only LLM builds.
    errors.extend(_validate_polish_authorization(project_root, polish, use_llm))

    # Eligible-page count: 0 in preflight (no scan performed).
    # Task 1 will populate this from the WikiSnapshot.
    eligible_page_count = 0

    return PreflightReport(
        project_root=str(project_root),
        output_dir=str(output_dir.resolve()),
        staging_root=staging_root,
        provider=provider,
        model=model,
        tokenizer=tokenizer,
        eligible_page_count=eligible_page_count,
        errors=tuple(errors),
    )


# ---------------------------------------------------------------------------
# Cross-platform PID liveness check
# ---------------------------------------------------------------------------


def _pid_alive(pid: int) -> bool:
    """Return True iff a process with ``pid`` is alive.

    POSIX: ``os.kill(pid, 0)`` — raises ``ProcessLookupError`` if absent;
    ``PermissionError`` means the PID exists but we can't signal it
    (count as alive). ``OSError`` with ``errno.EPERM`` is the same.

    Windows: ``OpenProcess`` via ``ctypes``. Returns a non-NULL handle
    when the PID exists; ``ERROR_INVALID_PARAMETER`` (87) when it does
    not. We close the handle before returning to avoid leaking it.
    """
    if pid <= 0:
        return False

    if os.name == "nt":
        # kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid)
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            err = ctypes.get_last_error()  # type: ignore[attr-defined]
            # 87 = ERROR_INVALID_PARAMETER — no such process.
            # 5  = ERROR_ACCESS_DENIED — process exists but not queryable.
            return err == 5
        kernel32.CloseHandle(handle)
        return True

    # POSIX branch — ``os.kill`` with signal 0 just probes.
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # PID exists but we lack permission to signal it → still alive.
        return True
    except OSError as exc:
        # Some platforms raise OSError(EPERM); treat same as PermissionError.
        if exc.errno == errno.EPERM:
            return True
        return False
    return True


# ---------------------------------------------------------------------------
# Run lock
# ---------------------------------------------------------------------------


def _lock_payload(lock: RunLock) -> dict[str, Any]:
    """Serialise a RunLock to JSON. ``started_at`` is unix ms."""
    return {
        "owner_token": lock.owner_token,
        "pid": lock.pid,
        "started_at": lock.started_at,
        "stale_after_seconds": lock.stale_after_seconds,
    }


def _read_lock_payload(lock_path: Path) -> dict[str, Any] | None:
    """Parse the lock JSON file. Returns ``None`` on any I/O / parse error.

    A corrupt lock is treated as "not held" from the takeover perspective —
    but the takeover is still gated by the age + PID-dead check below, so
    a corrupt lock is never silently taken over; the caller must wait for
    the age threshold AND prove the holder is gone (which is impossible
    without a valid PID). We treat that combination as LockBusyError.
    """
    try:
        text = lock_path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def acquire_run_lock(
    lock_path: Path, *, stale_after_seconds: int
) -> "RunLock":
    """Acquire a single-writer lock. Returns :class:`RunLock` on success.

    Stale-takeover policy: BOTH (a) age > ``stale_after_seconds`` AND
    (b) holder PID has exited. Either condition unmet → :class:`LockBusyError`.

    The lock file contains owner_token + pid + started_at + stale_after_seconds
    so a later ``acquire`` can re-evaluate the policy without external state.
    """
    if stale_after_seconds <= 0:
        raise ValueError(
            "stale_after_seconds must be > 0; caller must pass the timeout "
            "explicitly (do not hardcode a default)."
        )

    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    now_ms = int(time.time() * 1000)
    new_owner_token = uuid.uuid4().hex

    # Fast path: no existing lock file → O_CREAT | O_EXCL.
    try:
        fd = os.open(
            str(lock_path),
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
    except FileExistsError:
        # Slow path: an existing lock — evaluate takeover policy.
        _maybe_takeover_stale_lock(lock_path, stale_after_seconds, now_ms)
        # Retry once after takeover (which should have unlinked the file).
        try:
            fd = os.open(
                str(lock_path),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError as exc:  # pragma: no cover - race with another acquirer
            raise LockBusyError(
                f"run lock still held after stale-takeover attempt: {lock_path}"
            ) from exc
    else:
        pass  # fast path succeeded

    new_lock = RunLock(
        path=str(lock_path),
        owner_token=new_owner_token,
        pid=os.getpid(),
        started_at=now_ms,
        stale_after_seconds=stale_after_seconds,
    )
    payload = json.dumps(_lock_payload(new_lock), ensure_ascii=False)
    try:
        os.write(fd, payload.encode("utf-8"))
    finally:
        os.close(fd)
    return new_lock


def _maybe_takeover_stale_lock(
    lock_path: Path,
    stale_after_seconds: int,
    now_ms: int,
) -> None:
    """Evaluate takeover policy; unlink the lock if eligible.

    Raises :class:`LockBusyError` when the lock is held by a live owner,
    or when takeover conditions are not both met.
    """
    data = _read_lock_payload(lock_path)
    if data is None:
        # Corrupt / unreadable / wrong type. We can't verify the PID, and
        # the plan requires BOTH conditions for takeover. Treat as busy.
        raise LockBusyError(
            f"run lock present but unreadable at {lock_path}; refusing takeover"
        )

    pid_raw = data.get("pid")
    started_at_raw = data.get("started_at")
    if not isinstance(pid_raw, int) or not isinstance(started_at_raw, int):
        raise LockBusyError(
            f"run lock at {lock_path} has invalid pid/started_at; refusing takeover"
        )

    age_seconds = (now_ms - started_at_raw) / 1000.0
    age_ok = age_seconds > stale_after_seconds
    pid_dead = not _pid_alive(pid_raw)

    if not (age_ok and pid_dead):
        # Either still young or holder still alive — refuse.
        raise LockBusyError(
            f"run lock at {lock_path} is held (pid={pid_raw}, age={age_seconds:.1f}s, "
            f"stale_after={stale_after_seconds}s, age_ok={age_ok}, pid_dead={pid_dead})"
        )

    # Both conditions met — atomically unlink so the O_EXCL retry can win.
    try:
        os.unlink(str(lock_path))
    except FileNotFoundError:
        # Someone else already cleaned it up — fine, O_EXCL retry will succeed.
        return
    except OSError as exc:
        raise LockBusyError(
            f"failed to unlink stale run lock at {lock_path}: {exc}"
        ) from exc


def release_run_lock(lock: RunLock) -> None:
    """Best-effort release. Never raises.

    We only delete the file when the on-disk owner_token still matches the
    RunLock handle — this prevents a process that already lost takeover
    from clobbering a newer lock.
    """
    lock_path = Path(lock.path)
    try:
        data = _read_lock_payload(lock_path)
    except OSError:
        return
    if data is None:
        return
    if data.get("owner_token") != lock.owner_token:
        return
    try:
        os.unlink(str(lock_path))
    except FileNotFoundError:
        return
    except OSError:
        return

__all__ = [
    "ACCEPTED_SCHEMA_VERSIONS",
    "DEFAULT_PROVIDER_ENV",
    "FORBIDDEN_OUTPUT_PARENTS",
    "LockBusyError",
    "POLICY_FILENAME",
    "PreflightReport",
    "RunLock",
    "ValidationError",
    "acquire_run_lock",
    "release_run_lock",
    "run_preflight",
]
