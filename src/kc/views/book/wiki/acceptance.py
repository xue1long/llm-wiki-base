"""Deterministic, fail-closed release acceptance evidence."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .scanner import WikiScanError, scan_wiki_snapshot

MANUAL_GATES = (
    "real_provider_readability",
    "human_acceptance",
)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def derive_book_freshness(project_root: Path, manifest: dict[str, Any]) -> tuple[str, str]:
    """Derive freshness from the release snapshot and the current Wiki."""
    expected = manifest.get("snapshot_id") or manifest.get("wiki_snapshot_hash")
    if not isinstance(expected, str) or not expected:
        return "unknown", "release_snapshot_id_missing"
    try:
        current = scan_wiki_snapshot(Path(project_root) / "wiki")
    except (OSError, WikiScanError, ValueError):
        return "unknown", "current_wiki_snapshot_unavailable"
    if current.snapshot_id == expected:
        return "fresh", "snapshot_matches_release"
    return "stale", "snapshot_differs_from_release"


def _manifest_integrity(release_dir: Path, manifest: dict[str, Any]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    run_id = manifest.get("run_id")
    if not isinstance(run_id, str) or run_id != release_dir.name:
        errors.append("release_id_mismatch")
    expected_digest = manifest.get("release_manifest_hash")
    payload = {key: value for key, value in manifest.items() if key != "release_manifest_hash"}
    if not isinstance(expected_digest, str) or hashlib.sha256(_canonical(payload)).hexdigest() != expected_digest:
        errors.append("manifest_digest_mismatch")
    files = manifest.get("files")
    if not isinstance(files, dict):
        errors.append("manifest_files_missing")
    else:
        for name, expected in sorted(files.items()):
            relative = Path(str(name))
            target = release_dir / relative
            normalized_name = str(name).replace("\\", "/")
            if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != normalized_name:
                errors.append(f"unsafe_file:{name}")
            elif not target.is_file() or not isinstance(expected, str) or _sha(target) != expected:
                errors.append(f"file_hash_mismatch:{name}")
    return not errors, errors


def _check_provenance(manifest: dict[str, Any]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not isinstance(manifest.get("chapter_sources"), dict):
        errors.append("chapter_sources_missing")
    if manifest.get("editorial_state_hash") is not None:
        if not isinstance(manifest.get("section_source_ids"), dict):
            errors.append("section_source_ids_missing")
        if not isinstance(manifest.get("tutorial_path_ids"), list):
            errors.append("tutorial_path_ids_missing")
    return not errors, errors


def build_release_acceptance_report(
    project_root: Path,
    release_dir: Path,
    *,
    publication_status: str = "planned",
    expected_pointer_version: str | None = None,
) -> dict[str, Any]:
    """Build a stable report; no timestamp is included by design."""
    manifest_path = Path(release_dir) / "manifest.json"
    errors: list[str] = []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        manifest = {}
        errors.append("manifest_unreadable")
    if not isinstance(manifest, dict):
        manifest = {}
        errors.append("manifest_invalid")

    manifest_ok, manifest_errors = _manifest_integrity(Path(release_dir), manifest)
    provenance_ok, provenance_errors = _check_provenance(manifest)
    freshness, freshness_reason = derive_book_freshness(Path(project_root), manifest)
    release_status = manifest.get("release_status", "unknown")
    generation_mode = manifest.get("generation_mode", "unknown")
    llm_metadata = manifest.get("llm_metadata")
    llm_required = isinstance(generation_mode, str) and generation_mode.startswith("llm")
    if llm_required and not isinstance(llm_metadata, dict):
        errors.append("llm_metadata_missing")
    if release_status != "complete":
        errors.append("release_status_not_complete")
    budget_ok = True
    if llm_required:
        used = llm_metadata.get("llm_calls_used") if isinstance(llm_metadata, dict) else None
        limit = llm_metadata.get("max_llm_calls") if isinstance(llm_metadata, dict) else None
        budget_ok = isinstance(used, int) and isinstance(limit, int) and 0 <= used <= limit
        if not budget_ok:
            errors.append("llm_budget_evidence_missing_or_invalid")
    authorization = "not_applicable"
    if llm_required:
        authorization = "pass" if isinstance(llm_metadata, dict) and llm_metadata.get("external_llm_authorized") is True else "fail"
        if authorization == "fail":
            errors.append("external_llm_authorization_missing")
    source_gate = "not_applicable"
    if llm_required:
        source_gate = "pass" if isinstance(llm_metadata, dict) and (
            llm_metadata.get("source_allowlist_passed") is True and
            llm_metadata.get("sensitive_gate_passed") is True
        ) else "fail"
        if source_gate == "fail":
            errors.append("source_allowlist_or_sensitivity_evidence_missing")
    pointer = "not_applicable"
    if publication_status == "committed":
        if expected_pointer_version is not None:
            pointer = "pass" if expected_pointer_version == manifest.get("run_id") else "fail"
        else:
            current = Path(release_dir).parents[1] / "CURRENT.json"
            try:
                pointer_data = json.loads(current.read_text(encoding="utf-8"))
                pointer = "pass" if pointer_data.get("version") == manifest.get("run_id") else "fail"
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                pointer = "fail"
        if pointer == "fail":
            errors.append("current_pointer_invalid")

    automated_ok = (
        not errors and manifest_ok and provenance_ok and release_status == "complete"
        and freshness == "fresh" and budget_ok and authorization != "fail"
        and pointer in {"pass", "not_applicable"}
    )
    return {
        "schema_version": "release-acceptance-v1",
        "release_id": manifest.get("run_id"),
        "snapshot_id": manifest.get("snapshot_id"),
        "manifest_sha256": _sha(manifest_path) if manifest_path.is_file() else None,
        "build_outcome": release_status,
        "generation_mode": generation_mode,
        "freshness": freshness,
        "freshness_reason": freshness_reason,
        "approval": "pending",
        "checks": {
            "manifest_integrity": "pass" if manifest_ok else "fail",
            "chapter_provenance": "pass" if provenance_ok else "fail",
            "llm_budget": "pass" if budget_ok else "fail",
            "external_llm_authorization": authorization,
            "source_allowlist_and_sensitivity": source_gate,
            "current_pointer": pointer,
        },
        "automated_acceptance": "pass" if automated_ok else "fail",
        "automated_errors": sorted(set(errors + manifest_errors + provenance_errors)),
        "llm_failure_reasons": list(llm_metadata.get("failure_reasons", ())) if isinstance(llm_metadata, dict) else [],
        "manual_gates": dict.fromkeys(MANUAL_GATES, "pending"),
        "publication_status": publication_status,
    }


def write_release_acceptance_report(release_dir: Path, report: dict[str, Any]) -> Path:
    path = Path(release_dir) / "release-acceptance.json"
    path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    return path


def load_release_acceptance_report(release_dir: Path) -> dict[str, Any] | None:
    release_dir = Path(release_dir)
    path = release_dir / "release-acceptance.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        manifest = json.loads((release_dir / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or not isinstance(manifest, dict):
        return None
    if (
        payload.get("release_id") != manifest.get("run_id")
        or payload.get("snapshot_id") != manifest.get("snapshot_id")
        or payload.get("manifest_sha256") != _sha(release_dir / "manifest.json")
    ):
        return None
    return payload


__all__ = [
    "MANUAL_GATES", "build_release_acceptance_report", "derive_book_freshness",
    "load_release_acceptance_report", "write_release_acceptance_report",
]
