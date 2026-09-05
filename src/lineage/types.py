from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LineageHealth:
    integrity_ok: bool
    orphan_links: int
    pending_outbox: int = 0
    invalid_statuses: int = 0
    missing_artifacts: int = 0
    hash_mismatches: int = 0

    @property
    def ok(self) -> bool:
        return self.integrity_ok and not any((self.orphan_links, self.pending_outbox,
                                              self.invalid_statuses, self.missing_artifacts,
                                              self.hash_mismatches))


@dataclass(frozen=True)
class RawSourceChange:
    source_id: str
    source_path: str
    source_hash: str
    status: str


@dataclass(frozen=True)
class RawScanResult:
    complete: bool
    changes: tuple[RawSourceChange, ...]
