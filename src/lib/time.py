"""Small, UTC-first time primitives shared by persisted project data."""
from datetime import datetime, timezone


def now_aware() -> datetime:
    return datetime.now(timezone.utc)


def now_ms() -> int:
    return dt_to_ms(now_aware())


def now_iso(*, utc: bool = True) -> str:
    value = now_aware() if utc else datetime.now().astimezone()
    return value.isoformat()


def ms_to_dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def dt_to_ms(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)
