"""Import wiki from a ZIP archive."""
import logging
import zipfile
from pathlib import Path


_logger = logging.getLogger(__name__)


def import_wiki(archive_zip: Path, target_dir: Path) -> None:
    """Extract archive_zip into target_dir."""
    archive_zip = Path(archive_zip)
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_zip, "r") as zf:
        zf.extractall(target_dir)
    _logger.info(f"[import] extracted {archive_zip} → {target_dir}")
