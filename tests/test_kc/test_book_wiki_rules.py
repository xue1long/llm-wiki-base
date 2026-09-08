from dataclasses import FrozenInstanceError
from hashlib import sha256
from pathlib import Path

import pytest

from src.kc.views.book.wiki.rules import (
    BookRulesError,
    BookRulesSnapshot,
    load_book_rules,
)


def test_load_book_rules_returns_canonical_immutable_snapshot(tmp_path: Path) -> None:
    (tmp_path / "book.rules.md").write_bytes(b"\xef\xbb\xbfTitle\r\n\rBody\r\n")

    snapshot = load_book_rules(tmp_path)

    assert isinstance(snapshot, BookRulesSnapshot)
    assert snapshot.path == "book.rules.md"
    assert snapshot.text == "Title\n\nBody\n"
    assert snapshot.rules_hash == sha256(snapshot.text.encode("utf-8")).hexdigest()
    with pytest.raises(FrozenInstanceError):
        snapshot.text = "changed"  # type: ignore[misc]


@pytest.mark.parametrize("content", [b"", b" \t\r\n "])
def test_empty_or_whitespace_only_rules_fail_closed(
    tmp_path: Path, content: bytes
) -> None:
    (tmp_path / "book.rules.md").write_bytes(content)

    with pytest.raises(BookRulesError):
        load_book_rules(tmp_path)


def test_missing_rules_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(BookRulesError):
        load_book_rules(tmp_path)


def test_invalid_utf8_rules_fail_closed(tmp_path: Path) -> None:
    (tmp_path / "book.rules.md").write_bytes(b"valid\xff")

    with pytest.raises(BookRulesError):
        load_book_rules(tmp_path)


def test_read_error_fails_closed_without_exposing_contents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rules_path = tmp_path / "book.rules.md"
    rules_path.write_text("secret rules", encoding="utf-8")

    def fail_read(self: Path) -> bytes:
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "read_bytes", fail_read)

    with pytest.raises(BookRulesError) as exc_info:
        load_book_rules(tmp_path)

    assert "secret rules" not in str(exc_info.value)


def test_rules_file_is_read_once_per_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "book.rules.md").write_text("rules", encoding="utf-8")
    original_read_bytes = Path.read_bytes
    reads = 0

    def counted_read(self: Path) -> bytes:
        nonlocal reads
        reads += 1
        return original_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", counted_read)

    load_book_rules(tmp_path)

    assert reads == 1
