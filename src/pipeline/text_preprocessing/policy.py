"""Versioned, explicit readiness policy profiles."""

from __future__ import annotations

from .types import ContentKind, ContentProfile, ReadinessPolicy


def _profile(
    format: str,
    extraction_method: str,
    content_kind: ContentKind,
    *,
    minimum_units: int,
    minimum_chars: int,
    short_minimum_chars: int,
    short_requires_structure: bool,
    metadata_dominance_ratio: float = 0.65,
    repetition_warning_ratio: float = 0.3,
) -> ContentProfile:
    return ContentProfile(
        profile_id=f"{format}:{extraction_method}:{content_kind.value}",
        format=format,
        extraction_method=extraction_method,
        content_kind=content_kind,
        minimum_units=minimum_units,
        minimum_chars=minimum_chars,
        short_minimum_chars=short_minimum_chars,
        short_requires_structure=short_requires_structure,
        metadata_dominance_ratio=metadata_dominance_ratio,
        repetition_warning_ratio=repetition_warning_ratio,
    )


def _builtin_v1() -> ReadinessPolicy:
    prose = dict(minimum_units=1, minimum_chars=20, short_minimum_chars=2, short_requires_structure=True)
    title_definition = dict(minimum_units=2, minimum_chars=8, short_minimum_chars=2, short_requires_structure=True)
    list_profile = dict(minimum_units=2, minimum_chars=2, short_minimum_chars=1, short_requires_structure=True)
    code = dict(minimum_units=1, minimum_chars=1, short_minimum_chars=1, short_requires_structure=False)
    table = dict(minimum_units=1, minimum_chars=1, short_minimum_chars=1, short_requires_structure=False)
    return ReadinessPolicy(
        "content-policy-v1",
        (
            _profile("md", "native_text", ContentKind.PROSE, **prose),
            _profile("txt", "native_text", ContentKind.PROSE, **prose),
            _profile("md", "native_text", ContentKind.TITLE_DEFINITION, **title_definition),
            _profile("txt", "native_text", ContentKind.TITLE_DEFINITION, **title_definition),
            _profile("html", "html_text", ContentKind.TITLE_DEFINITION, **title_definition),
            _profile("md", "native_text", ContentKind.LIST, **list_profile),
            _profile("txt", "native_text", ContentKind.LIST, **list_profile),
            _profile("html", "html_text", ContentKind.LIST, **list_profile),
            _profile("md", "native_text", ContentKind.CODE, **code),
            _profile("txt", "native_text", ContentKind.CODE, **code),
            _profile("html", "html_text", ContentKind.CODE, **code),
            _profile("pdf", "pdf_text", ContentKind.PROSE, **prose),
            _profile("docx", "docx_text", ContentKind.PROSE, **prose),
            _profile("xlsx", "xlsx_cells", ContentKind.TABLE, **table),
            _profile("pdf", "pdf_text", ContentKind.TABLE, **table),
            _profile("image", "ocr", ContentKind.IMAGE_OCR, **prose),
            _profile("pdf", "ocr", ContentKind.IMAGE_OCR, **prose),
        ),
    )


def load_policy(policy_version: str = "content-policy-v1") -> ReadinessPolicy:
    if policy_version != "content-policy-v1":
        raise ValueError(f"unsupported policy version: {policy_version}")
    return _builtin_v1()


def select_profile(
    policy: ReadinessPolicy,
    *,
    format: str,
    extraction_method: str,
    content_kind: ContentKind,
) -> ContentProfile | None:
    try:
        kind = ContentKind(content_kind)
    except ValueError as exc:
        raise ValueError("content_kind is unknown") from exc
    return next(
        (
            profile
            for profile in policy.profiles
            if profile.format == format
            and profile.extraction_method == extraction_method
            and profile.content_kind is kind
        ),
        None,
    )


def serialize_policy(policy: ReadinessPolicy) -> dict[str, object]:
    return {
        "policy_version": policy.policy_version,
        "profiles": [
            {
                "profile_id": profile.profile_id,
                "format": profile.format,
                "extraction_method": profile.extraction_method,
                "content_kind": profile.content_kind.value,
                "minimum_units": profile.minimum_units,
                "minimum_chars": profile.minimum_chars,
                "short_minimum_chars": profile.short_minimum_chars,
                "short_requires_structure": profile.short_requires_structure,
                "metadata_dominance_ratio": profile.metadata_dominance_ratio,
                "repetition_warning_ratio": profile.repetition_warning_ratio,
            }
            for profile in policy.profiles
        ],
    }
