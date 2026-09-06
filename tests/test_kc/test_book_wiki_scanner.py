from __future__ import annotations

from pathlib import Path

import pytest

from src.kc.views.book.wiki.model import ContentBlock, PageRecord, WikiSnapshot
from src.kc.views.book.wiki.scanner import (
    SnapshotChangedError,
    WikiScanError,
    canonical_snapshot_json,
    scan_wiki_snapshot,
    snapshot_sha256,
)


def _page(root: Path, directory: str, page_id: str, title: str, body: str,
          *, relations: str = "[]", extra: str = "") -> Path:
    path = root / "wiki" / directory / f"{page_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    page_type = {"concepts": "concept", "entities": "entity", "synthesis": "synthesis", "sources": "source"}[directory]
    path.write_text(
        f"---\nid: {page_id}\ntitle: {title}\ntype: {page_type}\n"
        f"primary_taxonomy: writing\nrelations: {relations}\n{extra}---\n\n{body}",
        encoding="utf-8",
    )
    return path


def test_scans_eligible_pages_and_preserves_ordered_blocks(tmp_path: Path) -> None:
    _page(tmp_path, "concepts", "c1", "Concept", "preamble\n\n# First\nalpha\n# First\nbeta")
    _page(tmp_path, "entities", "e1", "Entity", "## Entity body\nvalue")
    _page(tmp_path, "synthesis", "s1", "Synthesis", "summary")
    _page(tmp_path, "sources", "source-1", "Excluded", "source body")
    (tmp_path / "wiki" / "_stubs").mkdir(parents=True)
    (tmp_path / "wiki" / "_stubs" / "stub.md").write_text("---\nid: stub-1\ntitle: Stub\ntype: entity\n---\n\nstub", encoding="utf-8")
    (tmp_path / "wiki" / "concepts" / ".hidden.md").write_text("bad", encoding="utf-8")

    snapshot = scan_wiki_snapshot(tmp_path / "wiki")

    assert [p.page_id for p in snapshot.pages] == ["c1", "e1", "s1"]
    assert snapshot.excluded_sources == ("source-1", "stub-1")
    blocks = snapshot.pages[0].content_blocks
    assert [(b.heading, b.body) for b in blocks] == [
        (None, "preamble"), ("First", "alpha"), ("First", "beta")
    ]
    assert [b.block_id for b in blocks] == ["c1:0", "c1:1", "c1:2"]


@pytest.mark.parametrize(
    "setup,match",
    [
        (lambda root: _page(root, "concepts", "same", "A", "body") and _page(root, "entities", "same", "B", "body"), "duplicate page id"),
        (lambda root: _page(root, "concepts", "a", "Same", "body") and _page(root, "entities", "b", "Same", "body"), "duplicate title"),
        (lambda root: (root / "wiki" / "concepts" / "bad.md").parent.mkdir(parents=True, exist_ok=True) or (root / "wiki" / "concepts" / "bad.md").write_text("---\nid: bad\ntitle: [\n---\n\nbody", encoding="utf-8"), "frontmatter"),
        (lambda root: _page(root, "concepts", "empty", "Empty", "   \n\t"), "empty body"),
    ],
)
def test_invalid_pages_fail_closed(tmp_path: Path, setup, match: str) -> None:
    setup(tmp_path)
    with pytest.raises(WikiScanError, match=match):
        scan_wiki_snapshot(tmp_path / "wiki")


def test_missing_frontmatter_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "wiki" / "concepts" / "bad.md"
    path.parent.mkdir(parents=True)
    path.write_text("# no frontmatter\nbody", encoding="utf-8")
    with pytest.raises(WikiScanError, match="frontmatter"):
        scan_wiki_snapshot(tmp_path / "wiki")


def test_invalid_utf8_and_symlink_escape_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "wiki" / "concepts" / "bad.md"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"\xff\xfe")
    with pytest.raises(WikiScanError, match="UTF-8"):
        scan_wiki_snapshot(tmp_path / "wiki")

    path.unlink()
    outside = tmp_path / "outside.md"
    outside.write_text("---\nid: out\ntitle: Out\ntype: concept\n---\n\nbody", encoding="utf-8")
    path.symlink_to(outside)
    with pytest.raises(WikiScanError, match="symlink"):
        scan_wiki_snapshot(tmp_path / "wiki")


def test_snapshot_detects_change_during_scan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _page(tmp_path, "concepts", "c1", "Concept", "body")
    original = Path.read_bytes
    calls = 0

    def changing_read(self: Path) -> bytes:
        nonlocal calls
        data = original(self)
        if self == path:
            calls += 1
            if calls == 2:
                return data.replace(b"body", b"changed")
        return data

    monkeypatch.setattr(Path, "read_bytes", changing_read)
    with pytest.raises(SnapshotChangedError, match="changed"):
        scan_wiki_snapshot(tmp_path / "wiki")


def test_snapshot_hash_is_stable_and_does_not_include_absolute_root(tmp_path: Path) -> None:
    _page(tmp_path, "concepts", "c1", "Concept", "body")
    one = scan_wiki_snapshot(tmp_path / "wiki")
    other_root = tmp_path / "other"
    _page(other_root, "concepts", "c1", "Concept", "body")
    two = scan_wiki_snapshot(other_root / "wiki")

    assert snapshot_sha256(one) == snapshot_sha256(two)
    canonical = canonical_snapshot_json(one)
    assert str(tmp_path) not in canonical
