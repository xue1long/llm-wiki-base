"""Frontmatter parsing used by ingest service (audit PR-2 Task F).

Pre-PR-2 bug: ``_get_ingested_paths`` and ``_find_source_page_by_raw_path``
in ``src/services/ingest.py`` parsed the wiki page frontmatter with a
hand-rolled line scanner that only handled the YAML block-list shape
emitted by the writer (``default_flow_style=False``):

    sources:
    - raw/sources/foo.md

Anyone — or any tool — that emits a different YAML shape (inline flow,
double-quoted entries, single-quoted entries, the empty ``[]`` form)
silently produced zero matches, breaking de-duplication:

    sources: [raw/sources/foo.md]      # inline flow — missed
    sources:
      - "raw/sources/foo.md"           # quoted entries — missed (kept as
                                       #   ``- "raw/sources/foo.md"`` and
                                       #   compared verbatim with the
                                       #   unquoted path the API sent in)

After PR-2: both helpers route through ``yaml.safe_load``, the same
frontmatter parser already used by ``src/wiki/storage/page_writer.py``.
The scanner is gone.
"""

from __future__ import annotations

from pathlib import Path

from src.services.ingest import (
    _find_source_page_by_raw_path,
    _get_ingested_paths,
    _normalize_raw_path,
    _page_id_from_text,
    _page_sources_from_text,
)


# ── normalisation ─────────────────────────────────────────────────────────


def test_normalize_strips_prefix_until_raw_sources():
    """Legacy absolute / partially-qualified paths collapse to ``raw/sources/…``."""
    assert _normalize_raw_path(
        "D:\\project\\subdir\\raw\\sources\\foo.md"
    ) == "raw/sources/foo.md"
    assert _normalize_raw_path(
        "knowledge/novel-wiki/raw/sources/bar.md"
    ) == "raw/sources/bar.md"
    assert _normalize_raw_path("raw/sources/baz.md") == "raw/sources/baz.md"


def test_normalize_passes_through_http_urls():
    """URL sources are not raw paths — let the caller decide what to do with them."""
    assert _normalize_raw_path("https://example.com/page") == "https://example.com/page"


def test_normalize_empty_returns_empty():
    assert _normalize_raw_path("") == ""


# ── frontmatter parsing ──────────────────────────────────────────────────


def test_parse_block_list_sources():
    text = (
        "---\n"
        "id: page-x\n"
        "sources:\n"
        "- raw/sources/a.md\n"
        "- raw/sources/b.md\n"
        "---\n\nBody"
    )
    assert _page_sources_from_text(text) == ["raw/sources/a.md", "raw/sources/b.md"]


def test_parse_inline_flow_sources():
    """Inline flow shape — the case the old line scanner silently missed."""
    text = (
        "---\n"
        "id: page-y\n"
        "sources: [raw/sources/a.md, raw/sources/b.md]\n"
        "---\n\nBody"
    )
    assert sorted(_page_sources_from_text(text)) == [
        "raw/sources/a.md",
        "raw/sources/b.md",
    ]


def test_parse_quoted_block_sources():
    """Quoted entries — the old scanner kept the quotes and never matched."""
    text = (
        "---\n"
        "id: page-z\n"
        "sources:\n"
        '  - "raw/sources/a.md"\n'
        "  - 'raw/sources/b.md'\n"
        "---\n\nBody"
    )
    assert sorted(_page_sources_from_text(text)) == [
        "raw/sources/a.md",
        "raw/sources/b.md",
    ]


def test_parse_empty_sources_list():
    text = "---\nid: page-q\nsources: []\n---\n\nBody"
    assert _page_sources_from_text(text) == []


def test_parse_missing_sources_field():
    text = "---\nid: page-r\ntitle: page\n---\n\nBody"
    assert _page_sources_from_text(text) == []


def test_parse_legacy_no_frontmatter_block():
    text = "Body without frontmatter at all."
    assert _page_sources_from_text(text) == []


def test_parse_skips_http_entries():
    """URLs in ``sources:`` are not raw paths and must be filtered out."""
    text = (
        "---\n"
        "id: page-s\n"
        "sources:\n"
        "- raw/sources/a.md\n"
        "- https://example.com/article\n"
        "---\n\nBody"
    )
    assert _page_sources_from_text(text) == ["raw/sources/a.md"]


def test_parse_tolerates_malformed_frontmatter():
    """A broken YAML block must not raise — return [] for the offending field."""
    text = (
        "---\n"
        "id: page-bad\n"
        "sources: [unclosed bracket\n"
        "---\n\nBody"
    )
    assert _page_sources_from_text(text) == []


def test_parse_id_field_round_trip():
    text = "---\nid: page-id-1\ntitle: x\n---\n\nBody"
    assert _page_id_from_text(text) == "page-id-1"


def test_parse_id_missing_returns_none():
    text = "---\ntitle: x\n---\n\nBody"
    assert _page_id_from_text(text) is None


# ── end-to-end on the wiki/ tree ────────────────────────────────────────


def _mk_page(sources_dir: Path, source_id: str, raw_paths: list[str]) -> None:
    """Write a minimal source page with the given ``sources`` list."""
    sources_dir.mkdir(parents=True, exist_ok=True)
    body_lines = "\n".join(f"- {p}" for p in raw_paths)
    (sources_dir / f"{source_id}.md").write_text(
        f"---\nid: {source_id}\ntitle: 源页\nsources:\n{body_lines}\n---\n\n",
        encoding="utf-8",
    )


def test_get_ingested_paths_handles_all_yaml_shapes(tmp_path):
    """The endpoint helper must extract raw paths regardless of YAML shape."""
    sources_dir = tmp_path / "wiki" / "sources"

    # Block-list shape (old behaviour).
    _mk_page(sources_dir, "block-a", ["raw/sources/foo.md"])
    # Inline flow shape — the old scanner missed this entirely.
    (sources_dir / "flow-b.md").write_text(
        "---\nid: flow-b\nsources: [raw/sources/bar.md]\n---\n\n",
        encoding="utf-8",
    )
    # Quoted entries — the old scanner kept the quotes.
    (sources_dir / "quoted-c.md").write_text(
        '---\nid: quoted-c\nsources:\n  - "raw/sources/baz.md"\n---\n\n',
        encoding="utf-8",
    )
    # Legacy absolute path — strip the prefix.
    (sources_dir / "legacy-d.md").write_text(
        f"---\nid: legacy-d\nsources:\n- {tmp_path}/raw/sources/legacy.md\n---\n\n",
        encoding="utf-8",
    )

    ingested = _get_ingested_paths(sources_dir, tmp_path)
    assert ingested == {
        "raw/sources/foo.md",
        "raw/sources/bar.md",
        "raw/sources/baz.md",
        "raw/sources/legacy.md",
    }


def test_find_source_page_finds_inline_flow_sources(tmp_path):
    """Pre-PR-2: ``_find_source_page_by_raw_path`` silently returned None for
    inline-flow frontmatter; ``reingest_source`` and ``delete_source`` then
    surfaced ``ValueError("No wiki source page found…")``. Post-PR-2 the
    helper finds the page across every YAML shape."""
    sources_dir = tmp_path / "wiki" / "sources"
    _mk_page(sources_dir, "block-page", ["raw/sources/foo.md"])
    (sources_dir / "flow-page.md").write_text(
        "---\nid: flow-page\nsources: [raw/sources/flow.md]\n---\n\n",
        encoding="utf-8",
    )
    (sources_dir / "quoted-page.md").write_text(
        '---\nid: quoted-page\nsources:\n  - "raw/sources/quoted.md"\n---\n\n',
        encoding="utf-8",
    )

    assert _find_source_page_by_raw_path(
        sources_dir, "raw/sources/foo.md"
    ) == "block-page"
    assert _find_source_page_by_raw_path(
        sources_dir, "raw/sources/flow.md"
    ) == "flow-page"
    assert _find_source_page_by_raw_path(
        sources_dir, "raw/sources/quoted.md"
    ) == "quoted-page"
    # A path that no page references — must not raise.
    assert _find_source_page_by_raw_path(
        sources_dir, "raw/sources/missing.md"
    ) is None


def test_find_source_page_handles_url_target(tmp_path):
    """A URL is not a raw path; the helper returns None without raising."""
    sources_dir = tmp_path / "wiki" / "sources"
    assert _find_source_page_by_raw_path(
        sources_dir, "https://example.com/page"
    ) is None
