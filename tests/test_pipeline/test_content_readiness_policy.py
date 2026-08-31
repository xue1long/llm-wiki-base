"""Tests for the versioned, explicit readiness policy registry."""

from __future__ import annotations

import json

import pytest

from src.pipeline.text_preprocessing import (
    ContentKind,
    ContentProfile,
    ReadinessPolicy,
    load_policy,
    select_profile,
    serialize_policy,
)


def _profile(**overrides: object) -> ContentProfile:
    values: dict[str, object] = {
        "profile_id": "md-native-prose",
        "format": "md",
        "extraction_method": "native_text",
        "content_kind": ContentKind.PROSE,
        "minimum_units": 1,
        "minimum_chars": 20,
        "short_minimum_chars": 2,
        "short_requires_structure": True,
        "metadata_dominance_ratio": 0.65,
        "repetition_warning_ratio": 0.3,
    }
    values.update(overrides)
    return ContentProfile(**values)


def test_builtin_policy_serializes_deterministically() -> None:
    first = json.dumps(serialize_policy(load_policy()), ensure_ascii=False, sort_keys=True)
    second = json.dumps(serialize_policy(load_policy()), ensure_ascii=False, sort_keys=True)

    assert first == second
    assert load_policy().policy_version == "content-policy-v1"


def test_profile_selection_is_explicit_and_has_no_unknown_fallback() -> None:
    policy = load_policy()

    assert select_profile(
        policy,
        format="md",
        extraction_method="native_text",
        content_kind=ContentKind.PROSE,
    ) is not None
    assert select_profile(
        policy,
        format="bin",
        extraction_method="native_text",
        content_kind=ContentKind.PROSE,
    ) is None


def test_policy_rejects_duplicate_profile_keys() -> None:
    with pytest.raises(ValueError, match="duplicate profile key"):
        ReadinessPolicy("test", (_profile(), _profile(profile_id="other")))


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"minimum_units": -1}, "threshold"),
        ({"minimum_chars": -1}, "threshold"),
        ({"short_minimum_chars": 21}, "short_minimum_chars"),
        ({"metadata_dominance_ratio": 2.0}, "ratio"),
    ],
)
def test_profile_rejects_invalid_thresholds(changes: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _profile(**changes)


def test_policy_rejects_missing_policy_version() -> None:
    with pytest.raises(ValueError, match="policy_version"):
        ReadinessPolicy("", (_profile(),))


def test_profile_rejects_unknown_content_kind() -> None:
    with pytest.raises(ValueError, match="content_kind"):
        _profile(content_kind="metadata_only")
