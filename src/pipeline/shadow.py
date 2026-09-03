"""Shadow mode: dual-run comparison between pipeline modes.

When RUFLO_SHADOW_MODE=true, the main path (candidate) writes to wiki as
usual, and the shadow path (legacy) writes to .index/shadow/<task_id>/.
A JSON comparison report is generated alongside.
"""

from __future__ import annotations
import json
import logging
import os
import time as _time
import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ShadowReport:
    source_count: int
    claim_count: int
    valid_claim_count: int
    evidence_count: int
    page_count: int
    differences: tuple[str, ...]
    llm_calls: int
    writer_calls: int
    elapsed_ms: int
    contract_version: str
    source_hash: str
    blocked: bool = False


def compare_contracts(parsed_candidate, document, registry, task_context) -> ShadowReport:
    """Compare an already parsed candidate without invoking pipeline stages."""
    started = _time.monotonic()
    claims = parsed_candidate.get("claims", []) if isinstance(parsed_candidate, dict) else getattr(parsed_candidate, "claims", [])
    valid = 0
    evidence = 0
    differences = []
    visible = set(registry.visible_block_ids())
    for claim in claims:
        ids = claim.get("evidence_block_ids", claim.get("evidence_refs", [])) if isinstance(claim, dict) else []
        if ids and all(block_id in visible for block_id in ids):
            valid += 1
            evidence += len(ids)
        else:
            differences.append("invalid_evidence")
    source_text = document if isinstance(document, str) else str(document)
    source_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    return ShadowReport(
        source_count=1, claim_count=len(claims), valid_claim_count=valid,
        evidence_count=evidence, page_count=len(parsed_candidate.get("pages", [])) if isinstance(parsed_candidate, dict) else 0,
        differences=tuple(sorted(set(differences))), llm_calls=0, writer_calls=0,
        elapsed_ms=int((_time.monotonic() - started) * 1000),
        contract_version=getattr(task_context, "contract_version", "v1"), source_hash=source_hash,
        blocked=bool(claims) and valid == 0,
    )


@dataclass(frozen=True)
class RollbackResult:
    status: str
    task_id: str
    path: Path | None = None


def rollback_task(task_id: str, project_root: Path) -> RollbackResult:
    """Quarantine an unfinished staged task; never modify published Wiki."""
    if not task_id or Path(task_id).name != task_id:
        raise ValueError("unsafe task id")
    root = Path(project_root)
    staging = root / ".index" / "staging" / task_id
    if not staging.exists():
        return RollbackResult("not_found", task_id)
    if (staging / "publish.marker").exists():
        return RollbackResult("published", task_id, staging)
    target = root / ".index" / "quarantine" / task_id
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    shutil.move(str(staging), str(target))
    return RollbackResult("quarantined", task_id, target)


def compare_evidence_contracts(parsed_candidate, document, registry, task_id: str) -> dict:
    """Compare adapters using one already-parsed Analyzer result."""
    from dataclasses import asdict, is_dataclass

    from src.kc import api as kc_api
    from src.kc.adapters.candidate_v2 import adapt_candidate

    raw = asdict(parsed_candidate) if is_dataclass(parsed_candidate) else parsed_candidate
    legacy = None
    legacy_error = None
    try:
        legacy = kc_api.candidate_to_payload(raw, document, visible_block_ids=set(registry.visible_block_ids()))
    except (ValueError, KeyError, TypeError) as exc:
        legacy_error = type(exc).__name__
    v2 = adapt_candidate(parsed_candidate, document, registry)
    return {
        "task_id": task_id,
        "contract_version": "v2",
        "llm_calls": 0,
        "legacy": {
            "claim_count": len(legacy.get("claims", [])) if legacy else 0,
            "error": legacy_error,
        },
        "v2": {
            "claim_count": v2.valid_claim_count,
            "rejected_claim_count": len(v2.rejected_claims),
        },
        "differences": {
            "claim_count_delta": v2.valid_claim_count - (len(legacy.get("claims", [])) if legacy else 0),
            "legacy_error": legacy_error,
        },
    }


async def run_shadow_ingest(
    paths,
    source_path,
    source_text: str,
    provider,
    folder_context: str = "",
    task_id: str = "test",
    shadow_mode: str = "legacy",
):
    """Run ingest in *shadow_mode* and write results to .index/shadow/<task_id>/.

    Returns (shadow_pages, shadow_meta) or (None, None) on failure.
    Shadow failure must never block the main path.
    """
    from .ingest import generate_ingest

    old_mode = os.environ.get("RUFLO_PIPELINE_MODE")
    try:
        os.environ["RUFLO_PIPELINE_MODE"] = shadow_mode
        shadow_pages, shadow_extra, shadow_meta = await generate_ingest(
            paths=paths,
            source_path=source_path,
            source_text=source_text,
            provider=provider,
            folder_context=folder_context,
            task_id=task_id,
        )
    except Exception as exc:
        _logger.warning(
            "[shadow] shadow ingest failed for %s: %s", task_id, exc,
        )
        return None, None
    finally:
        if old_mode is None:
            os.environ.pop("RUFLO_PIPELINE_MODE", None)
        else:
            os.environ["RUFLO_PIPELINE_MODE"] = old_mode

    # Write shadow output
    shadow_dir = paths.index / "shadow" / task_id
    shadow_dir.mkdir(parents=True, exist_ok=True)

    shadow_payload = {
        "task_id": task_id,
        "source_path": str(source_path),
        "mode": shadow_mode,
        "timestamp": int(_time.time() * 1000),
        "page_count": len(shadow_pages),
        "extra_count": len(shadow_extra),
        "meta": {k: v for k, v in shadow_meta.items() if k != "analysis"},
        "pages": [
            {
                "id": p.id,
                "type": p.type.value,
                "title": p.title,
                "grade": p.grade,
                "body_len": len(p.body),
            }
            for p in shadow_pages
        ],
    }
    (shadow_dir / "output.json").write_text(
        json.dumps(shadow_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _logger.info(
        "[shadow] wrote %d shadow pages to %s", len(shadow_pages), shadow_dir,
    )
    return shadow_pages, shadow_meta


def write_comparison_report(
    shadow_dir: Path,
    main_pages: list,
    shadow_pages: list | None,
    main_meta: dict,
    shadow_meta: dict | None,
    task_id: str,
) -> Path:
    """Write a comparison report between main and shadow runs.

    Returns path to the report file.
    """
    shadow_dir.mkdir(parents=True, exist_ok=True)

    # Main stats
    main_types = {}
    main_grades = {}
    for p in main_pages:
        main_types[p.type.value] = main_types.get(p.type.value, 0) + 1
        main_grades[p.grade] = main_grades.get(p.grade, 0) + 1

    # Shadow stats (if available)
    shadow_types = {}
    shadow_grades = {}
    if shadow_pages:
        for p in shadow_pages:
            shadow_types[p.type.value] = shadow_types.get(p.type.value, 0) + 1
            shadow_grades[p.grade] = shadow_grades.get(p.grade, 0) + 1

    report = {
        "task_id": task_id,
        "timestamp": int(_time.time() * 1000),
        "main": {
            "page_count": len(main_pages),
            "type_distribution": main_types,
            "grade_distribution": main_grades,
            "rejected": main_meta.get("rejected", False),
            "needs_review": main_meta.get("needs_review", False),
        },
        "shadow": {
            "page_count": len(shadow_pages) if shadow_pages else 0,
            "type_distribution": shadow_types,
            "grade_distribution": shadow_grades,
            "rejected": shadow_meta.get("rejected", False) if shadow_meta else None,
            "needs_review": shadow_meta.get("needs_review", False) if shadow_meta else None,
            "available": shadow_pages is not None,
        },
        "comparison": {
            "page_count_delta": (
                len(main_pages) - len(shadow_pages)
                if shadow_pages else None
            ),
            "shared_types": sorted(set(main_types) & set(shadow_types)),
            "main_only_types": sorted(set(main_types) - set(shadow_types)),
            "shadow_only_types": sorted(set(shadow_types) - set(main_types)),
        },
    }

    report_path = shadow_dir / "comparison.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _logger.info("[shadow] comparison report written to %s", report_path)
    return report_path
