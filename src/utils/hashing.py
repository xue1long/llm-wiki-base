"""Small hashing helpers shared by scripts and services."""

from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_file(path: str | Path, chunk_size: int = 1 << 16) -> str:
    digest = hashlib.sha256()
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()
