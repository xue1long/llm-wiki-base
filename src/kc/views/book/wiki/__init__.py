"""Wiki-to-Book V3.2 wiki compiler package (Task 0+).

This package is the implementation locus for the V3.2 "可审计的 Wiki 拼装器"
plan. Each task in `docs/superpowers/plans/2026-09-05-wiki-to-book-v3.md`
adds one or more modules here.

Task 0 ships:
- ``preflight`` — fail-closed preflight + cross-platform single-writer run lock.

Subsequent tasks (1–8) extend this package; this ``__init__`` re-exports the
public Task 0 surface so callers can ``from src.kc.views.book.wiki import run_preflight``.
"""
from .preflight import (
    LockBusyError,
    PreflightReport,
    RunLock,
    ValidationError,
    acquire_run_lock,
    release_run_lock,
    run_preflight,
)
from .compiler import BuildArtifact, PublishReport, compile_book, publish_book, resolve_active_version
from .editorial_state import (
    BookEditorialState, build_editorial_state, editorial_state_hash,
    load_editorial_state, save_editorial_state, validate_editorial_state,
)
from .tutorial_path import PathStep, TutorialPath, validate_tutorial_paths
from .polish_llm import GeneratedChapter, GeneratedSection, generate_chapter_body
from .quality_gate import QualityGateReport, check_quality_gate, evaluate_quality_gate
from .rubric import EvidenceLocator, RubricSpec, load_rubric, load_rubric_specs
from .reader_tasks import ReaderTaskReport, ReaderTaskRunner, run_reader_task, run_reader_tasks, task_pass_rate
from .encyclopedic_outline import EncyclopedicUnavailable, generate_encyclopedic_outline, safe_summary
from .cross_links import (
    _NAMESPACE_RELATIONS, build_cross_link_candidates, dangling_cross_links,
    find_dangling_cross_links, validate_cross_links,
)
from .theme_outline import (
    ThemeOutlineError, load_theme_outline, plan_theme_outline,
    place_page_summaries, save_theme_outline, validate_theme_outline,
)
from .acceptance import (
    MANUAL_GATES, build_release_acceptance_report, derive_book_freshness,
    load_release_acceptance_report, write_release_acceptance_report,
)
from .partition import (
    CandidateDecision, GateMetrics, GovernanceConfig, ReaderProfile,
    SeriesGateResult, evaluate_series_gate,
)
from .series_model import SCHEMA_VERSION as SERIES_MANIFEST_SCHEMA_VERSION, BookManifest, SeriesManifest, canonical_digest, transition_status
from .series_validate import (
    dependency_report, detect_dependency_cycles, read_legacy_manifest,
    validate_book_manifest, validate_release_files, validate_series_manifest,
)

__all__ = [
    "LockBusyError",
    "PreflightReport",
    "RunLock",
    "ValidationError",
    "acquire_run_lock",
    "release_run_lock",
    "run_preflight",
    "BuildArtifact",
    "PublishReport",
    "compile_book",
    "publish_book",
    "resolve_active_version",
    "BookEditorialState", "build_editorial_state", "editorial_state_hash",
    "load_editorial_state", "save_editorial_state", "validate_editorial_state",
    "PathStep", "TutorialPath", "validate_tutorial_paths",
    "GeneratedChapter", "GeneratedSection", "generate_chapter_body",
    "QualityGateReport", "check_quality_gate", "evaluate_quality_gate", "EvidenceLocator", "RubricSpec", "load_rubric", "load_rubric_specs",
    "ReaderTaskReport", "ReaderTaskRunner", "run_reader_task", "run_reader_tasks", "task_pass_rate",
    "EncyclopedicUnavailable", "generate_encyclopedic_outline", "safe_summary",
    "build_cross_link_candidates", "validate_cross_links",
    "find_dangling_cross_links", "dangling_cross_links", "_NAMESPACE_RELATIONS",
    "ThemeOutlineError", "load_theme_outline", "plan_theme_outline", "place_page_summaries", "save_theme_outline", "validate_theme_outline",
    "MANUAL_GATES", "build_release_acceptance_report", "derive_book_freshness",
    "load_release_acceptance_report", "write_release_acceptance_report",
    "CandidateDecision", "GateMetrics", "GovernanceConfig", "ReaderProfile", "SeriesGateResult", "evaluate_series_gate",
    "SERIES_MANIFEST_SCHEMA_VERSION", "BookManifest", "SeriesManifest", "canonical_digest", "transition_status",
    "dependency_report", "detect_dependency_cycles", "read_legacy_manifest",
    "validate_book_manifest", "validate_release_files", "validate_series_manifest",
]
