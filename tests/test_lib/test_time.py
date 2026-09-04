from datetime import datetime, timezone
from pathlib import Path
import re

from src.lib.time import dt_to_ms, ms_to_dt, now_aware, now_iso, now_ms


def test_now_ms_is_integer_and_now_aware_is_utc():
    assert isinstance(now_ms(), int)
    assert now_aware().tzinfo == timezone.utc


def test_now_iso_is_utc_iso8601():
    parsed = datetime.fromisoformat(now_iso())
    assert parsed.tzinfo == timezone.utc


def test_millisecond_round_trip():
    original = datetime(2026, 9, 4, 12, 34, 56, 789000, tzinfo=timezone.utc)
    assert ms_to_dt(dt_to_ms(original)) == original


def test_naive_datetime_is_interpreted_as_utc():
    naive = datetime(2026, 9, 4, 12, 34, 56, 789000)
    assert dt_to_ms(naive) == dt_to_ms(naive.replace(tzinfo=timezone.utc))


def test_production_has_no_duplicate_now_ms_definitions():
    definitions = []
    for path in Path("src").rglob("*.py"):
        definitions.extend(
            re.findall(r"^def _now_ms\s*\(", path.read_text(encoding="utf-8"), re.MULTILINE)
        )
    assert definitions == []
