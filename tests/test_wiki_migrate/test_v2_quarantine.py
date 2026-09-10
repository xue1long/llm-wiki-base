import hashlib
import json
from pathlib import Path

from src.wiki.migrate.v2_quarantine import (
    extract_quarantine_metadata,
    is_invalid_card,
    raw_sha256,
    write_quarantine,
)


def test_detect_invalid_card_by_filename():
    assert is_invalid_card("invalid_BV1tdPDzQEpa.md")
    assert is_invalid_card(Path("invalid_x.md"))
    assert not is_invalid_card("BV1tdPDzQEpa.md")


def test_extract_metadata_keeps_original_fields_and_reason():
    frontmatter = {
        "uid": "20260403-D2A1",
        "bv": "BV1tdPDzQEpa",
        "source": "10_raw/x.md",
        "invalid_reason": "content_too_sparse",
        "uploader": "AI靓匠",
        "video_published_at": "2026-03-09",
    }

    metadata = extract_quarantine_metadata(frontmatter)

    assert metadata["reason"] == "content_too_sparse"
    assert metadata["invalid_reason"] == "content_too_sparse"
    assert metadata["uid"] == "20260403-D2A1"
    assert metadata["uploader"] == "AI靓匠"
    assert metadata["source"] == "10_raw/x.md"


def test_raw_sha256_is_stable_for_text_and_bytes():
    expected = hashlib.sha256("原始内容".encode("utf-8")).hexdigest()
    assert raw_sha256("原始内容") == expected
    assert raw_sha256("原始内容".encode("utf-8")) == expected


def test_write_quarantine_contains_reason_and_hash_but_not_main_wiki(tmp_path: Path):
    body = "原始 body 内容..."
    write_quarantine(
        slug="invalid_BV1tdPDzQEpa",
        metadata={"reason": "content_too_sparse", "bv": "BV1tdPDzQEpa"},
        body=body,
        target_root=tmp_path,
    )

    qdir = tmp_path / ".index" / "quarantine"
    page = qdir / "invalid_BV1tdPDzQEpa.md"
    assert page.exists()
    assert body in page.read_text(encoding="utf-8")
    assert raw_sha256(body) in page.read_text(encoding="utf-8")
    judgment = json.loads((qdir / "judgments.jsonl").read_text(encoding="utf-8").strip())
    assert judgment["slug"] == "invalid_BV1tdPDzQEpa"
    assert judgment["reason"] == "content_too_sparse"
    assert judgment["raw_sha256"] == raw_sha256(body)
    assert not (tmp_path / "wiki" / "concepts" / "invalid_BV1tdPDzQEpa.md").exists()
    assert not (tmp_path / "wiki" / "sources" / "invalid_BV1tdPDzQEpa.md").exists()


def test_write_quarantine_rejects_path_traversal(tmp_path: Path):
    try:
        write_quarantine("../escape", {}, "body", tmp_path)
    except ValueError as exc:
        assert "slug" in str(exc)
    else:
        raise AssertionError("unsafe quarantine slug was accepted")
