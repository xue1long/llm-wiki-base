"""Tests for src.wiki.types."""
import datetime

from src.wiki.core.types import (
    PageType,
    WikiPage,
    make_review_item,
    _coerce_ts_ms,
    _to_iso_dt,
)


def test_page_type_enum():
    assert PageType.SOURCE == "source"
    assert PageType.ENTITY == "entity"
    assert PageType.CONCEPT == "concept"
    assert PageType.SYNTHESIS == "synthesis"


def test_wiki_page_round_trip_frontmatter():
    page = WikiPage(
        id="abc", title="Test", type=PageType.ENTITY,
        sources=["raw/sources/foo.pdf"],
        created_at=1000, updated_at=2000, body="Hello world",
    )
    d = page.to_frontmatter_dict()
    assert d["id"] == "abc"
    assert d["type"] == "entity"
    assert d["sources"] == ["raw/sources/foo.pdf"]

    restored = WikiPage.from_dict(d, body="Hello world")
    assert restored.id == "abc"
    assert restored.type == PageType.ENTITY
    assert restored.body == "Hello world"


def test_review_item_normalized_title():
    item = make_review_item(
        item_id="rev-1", type_="missing-page",
        title="Missing page: Foo",
        detail="...", confidence=0.9,
    )
    assert item.normalized_title == "missing page: foo"
    assert item.status == "open"


def test_wiki_page_defaults():
    p = WikiPage(id="x", title="X", type=PageType.SOURCE)
    assert p.sources == []
    assert p.created_at == 0
    assert p.body == ""


# --- T-F2: timestamp coercion regression tests -----------------------------

ISO_DATE = "2026-08-10"
ISO_DATETIME = "2026-08-10T12:34:56"
ISO_DATE_MS = 1786320000000  # 2026-08-10 00:00:00 UTC in epoch ms


def test_coerce_ts_ms_int_passthrough():
    assert _coerce_ts_ms(ISO_DATE_MS) == ISO_DATE_MS
    assert _coerce_ts_ms(0) == 0


def test_coerce_ts_ms_numeric_string():
    assert _coerce_ts_ms(str(ISO_DATE_MS)) == ISO_DATE_MS
    assert _coerce_ts_ms(f"'{ISO_DATE_MS}'") == ISO_DATE_MS
    assert _coerce_ts_ms(f'"{ISO_DATE_MS}"') == ISO_DATE_MS


def test_coerce_ts_ms_iso_date_string():
    assert _coerce_ts_ms(ISO_DATE) == ISO_DATE_MS
    assert _coerce_ts_ms(f"'{ISO_DATE}'") == ISO_DATE_MS


def test_coerce_ts_ms_iso_datetime_string():
    # '2026-08-10T12:34:56' as naive datetime in local tz — we accept any
    # int output; just confirm it parses and produces epoch ms.
    out = _coerce_ts_ms(ISO_DATETIME)
    assert isinstance(out, int)
    assert out > 0


def test_coerce_ts_ms_iso_with_z():
    out = _coerce_ts_ms("2026-08-10T00:00:00Z")
    assert isinstance(out, int)
    assert out > 0


def test_coerce_ts_ms_none_empty_returns_default():
    assert _coerce_ts_ms(None) == 0
    assert _coerce_ts_ms("") == 0
    assert _coerce_ts_ms("   ") == 0
    assert _coerce_ts_ms(None, default=42) == 42


def test_coerce_ts_ms_garbage_returns_default():
    assert _coerce_ts_ms("not a date") == 0
    assert _coerce_ts_ms(["2026-08-10"]) == 0
    assert _coerce_ts_ms({"when": "2026-08-10"}) == 0
    assert _coerce_ts_ms(True) == 0  # bool rejected (int subclass trap)


def test_from_dict_coerces_iso_strings_in_timestamps():
    """The V4 schema requires int timestamps; ISO strings must be coerced
    on load so downstream heat/lint/vector code can assume int."""
    d = {
        "id": "x",
        "title": "X",
        "type": "source",
        "sources": [],
        "relations": [],
        "tags": [],
        "created_at": f"'{ISO_DATE}'",
        "updated_at": f"'{ISO_DATE}'",
        "verified_at": str(ISO_DATE_MS),
        "valid_from": f"'{ISO_DATE}'",
        "valid_to": ISO_DATE_MS,
        "last_used_at": "0",
    }
    page = WikiPage.from_dict(d, body="")
    assert page.created_at == ISO_DATE_MS
    assert page.updated_at == ISO_DATE_MS
    assert page.verified_at == ISO_DATE_MS
    assert page.valid_from == ISO_DATE_MS
    assert page.valid_to == ISO_DATE_MS
    assert page.last_used_at == 0
    assert all(
        isinstance(getattr(page, attr), int)
        for attr in ("created_at", "updated_at", "verified_at", "valid_from", "valid_to", "last_used_at")
    )


def test_from_dict_preserves_int_timestamps_unchanged():
    d = {
        "id": "x",
        "title": "X",
        "type": "source",
        "sources": [],
        "relations": [],
        "tags": [],
        "created_at": ISO_DATE_MS,
        "updated_at": ISO_DATE_MS,
        "verified_at": 0,
        "last_used_at": 0,
    }
    page = WikiPage.from_dict(d, body="")
    assert page.created_at == ISO_DATE_MS
    assert page.updated_at == ISO_DATE_MS


# --- V5 schema (5.0.0): producers emit ISO 8601 (YAML-native) ---

def test_to_iso_dt_from_datetime_passes_through():
    dt = datetime.datetime(2026, 8, 10, 12, 34, 56, tzinfo=datetime.timezone.utc)
    assert _to_iso_dt(dt) is dt


def test_to_iso_dt_tags_naive_as_utc():
    dt = datetime.datetime(2026, 8, 10, 12, 34, 56)  # naive
    out = _to_iso_dt(dt)
    assert out is not None
    assert out.tzinfo is not None


def test_to_iso_dt_from_int_ms():
    out = _to_iso_dt(ISO_DATE_MS)
    assert isinstance(out, datetime.datetime)
    assert int(out.timestamp() * 1000) == ISO_DATE_MS


def test_to_iso_dt_from_iso_string():
    out = _to_iso_dt("2026-08-10T12:34:56+00:00")
    assert isinstance(out, datetime.datetime)
    assert out == datetime.datetime(2026, 8, 10, 12, 34, 56, tzinfo=datetime.timezone.utc)


def test_to_iso_dt_zero_and_none_become_none():
    assert _to_iso_dt(0) is None
    assert _to_iso_dt(None) is None
    assert _to_iso_dt("") is None


def test_to_iso_dt_bool_rejected():
    # bool is int subclass trap
    assert _to_iso_dt(True) is None


def test_wiki_page_to_frontmatter_emits_datetime_objects():
    """V5 contract: frontmatter timestamps are datetime objects so PyYAML
    emits them as unquoted ``!!timestamp`` scalars."""
    page = WikiPage(
        id="x", title="X", type=PageType.SOURCE,
        created_at=ISO_DATE_MS, updated_at=ISO_DATE_MS,
    )
    fm = page.to_frontmatter_dict()
    assert isinstance(fm["created_at"], datetime.datetime)
    assert isinstance(fm["updated_at"], datetime.datetime)
    assert int(fm["created_at"].timestamp() * 1000) == ISO_DATE_MS


def test_wiki_page_v5_round_trip_through_yaml_safe_load():
    """PyYAML's implicit resolver parses V5 ISO timestamps to datetime."""
    import yaml

    page = WikiPage(
        id="x", title="X", type=PageType.SOURCE,
        created_at=ISO_DATE_MS, updated_at=ISO_DATE_MS,
    )
    fm = page.to_frontmatter_dict()
    dumped = yaml.safe_dump(fm, allow_unicode=True)
    # Must NOT contain the legacy ms int (proves we're not emitting ms).
    assert "1786320000000" not in dumped
    # Must contain the ISO date in unquoted YAML-native timestamp form.
    assert "2026-08-10" in dumped

    loaded = yaml.safe_load(dumped)
    assert isinstance(loaded["created_at"], datetime.datetime)
    assert isinstance(loaded["updated_at"], datetime.datetime)
    assert int(loaded["created_at"].timestamp() * 1000) == ISO_DATE_MS

    # Then re-load through WikiPage.from_dict to ensure round-trip
    restored = WikiPage.from_dict(loaded, body="")
    assert restored.created_at == ISO_DATE_MS
    assert restored.updated_at == ISO_DATE_MS


def test_from_dict_accepts_datetime_object():
    """YAML-native loader returns datetime; from_dict must coerce via _coerce_ts_ms."""
    dt = datetime.datetime(2026, 8, 10, tzinfo=datetime.timezone.utc)
    d = {
        "id": "x", "title": "X", "type": "source",
        "sources": [], "relations": [], "tags": [],
        "created_at": dt,
        "updated_at": dt,
    }
    page = WikiPage.from_dict(d, body="")
    assert page.created_at == int(dt.timestamp() * 1000)
    assert page.updated_at == int(dt.timestamp() * 1000)
