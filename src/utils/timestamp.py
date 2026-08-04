"""Timestamp utilities for WikiPage and other models.

Provides ISO 8601 timestamp helpers with UTC timezone.
All timestamps are stored as strings in ISO 8601 format: "2024-08-04T10:30:00Z"
"""
from datetime import datetime, timezone, timedelta
from typing import Optional


def now_iso() -> str:
    """Return current UTC timestamp as ISO 8601 string.

    Example: "2024-08-04T10:30:00.123456Z"
    """
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def now_iso_seconds() -> str:
    """Return current UTC timestamp as ISO 8601 string (seconds precision, no microseconds).

    Example: "2024-08-04T10:30:00Z"
    """
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso(timestamp: str) -> Optional[datetime]:
    """Parse ISO 8601 timestamp string to datetime.

    Args:
        timestamp: ISO 8601 string like "2024-08-04T10:30:00Z"

    Returns:
        datetime object or None if timestamp is empty/invalid
    """
    if not timestamp:
        return None

    try:
        # Handle 'Z' suffix (UTC)
        if timestamp.endswith("Z"):
            timestamp = timestamp[:-1] + "+00:00"
        return datetime.fromisoformat(timestamp)
    except (ValueError, AttributeError):
        return None


def iso_to_unix_ms(timestamp: str) -> int:
    """Convert ISO 8601 timestamp to Unix milliseconds.

    Args:
        timestamp: ISO 8601 string like "2024-08-04T10:30:00Z"

    Returns:
        Unix milliseconds, or 0 if timestamp is empty/invalid
    """
    dt = parse_iso(timestamp)
    if dt is None:
        return 0
    return int(dt.timestamp() * 1000)


def unix_ms_to_iso(unix_ms: int) -> str:
    """Convert Unix milliseconds to ISO 8601 timestamp.

    Args:
        unix_ms: Unix milliseconds

    Returns:
        ISO 8601 string, or empty string if unix_ms is 0
    """
    if unix_ms == 0:
        return ""
    try:
        dt = datetime.fromtimestamp(unix_ms / 1000, tz=timezone.utc)
        return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except (ValueError, OSError):
        return ""


def is_valid_iso(timestamp: str) -> bool:
    """Check if timestamp is a valid ISO 8601 string.

    Args:
        timestamp: String to validate

    Returns:
        True if valid ISO 8601, False otherwise
    """
    return parse_iso(timestamp) is not None


def compare_timestamps(ts1: str, ts2: str) -> int:
    """Compare two ISO 8601 timestamps.

    Args:
        ts1: First timestamp
        ts2: Second timestamp

    Returns:
        -1 if ts1 < ts2
         0 if ts1 == ts2
         1 if ts1 > ts2
        None if either is invalid
    """
    dt1 = parse_iso(ts1)
    dt2 = parse_iso(ts2)

    if dt1 is None or dt2 is None:
        return None

    if dt1 < dt2:
        return -1
    elif dt1 > dt2:
        return 1
    else:
        return 0


def timestamp_diff_seconds(ts1: str, ts2: str) -> Optional[float]:
    """Calculate difference between two timestamps in seconds.

    Args:
        ts1: First timestamp
        ts2: Second timestamp

    Returns:
        Difference in seconds (ts1 - ts2), or None if either is invalid
    """
    dt1 = parse_iso(ts1)
    dt2 = parse_iso(ts2)

    if dt1 is None or dt2 is None:
        return None

    return (dt1 - dt2).total_seconds()


def timestamp_diff_days(ts1: str, ts2: str) -> Optional[float]:
    """Calculate difference between two timestamps in days.

    Args:
        ts1: First timestamp
        ts2: Second timestamp

    Returns:
        Difference in days (ts1 - ts2), or None if either is invalid
    """
    seconds = timestamp_diff_seconds(ts1, ts2)
    if seconds is None:
        return None
    return seconds / 86400.0
