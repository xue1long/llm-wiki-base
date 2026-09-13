"""Copy-only adapters for supported Skill sources."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterable

from .types import FileEntry


def copy_local_skill(source: Path, destination: Path, files: Iterable[FileEntry]) -> None:
    """Copy the already-inspected file list without executing package content."""

    source = Path(source)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for entry in files:
        target = destination / Path(entry.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / Path(entry.path), target)
