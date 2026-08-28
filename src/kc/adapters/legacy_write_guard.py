"""Small fail-closed guard for migration-time writes."""


class WriteDenied(RuntimeError):
    """Raised when a write cannot be proven safe."""


def require_write_authority(
    *, verified: bool, source_id: str, expected_version: int, current_version: int
) -> bool:
    if not verified:
        raise WriteDenied("unverified knowledge cannot be published")
    if not source_id:
        raise WriteDenied("a source is required for publication")
    if expected_version != current_version:
        raise WriteDenied("write version conflict")
    return True
