"""Export wiki to a portable ZIP archive (no .index/lancedb/)."""
import logging
import zipfile
from pathlib import Path

from ..storage.ensure import ensure_knowledge_base
from ..core.paths import WikiPaths


_logger = logging.getLogger(__name__)


def export_wiki(paths: WikiPaths, output_zip: Path) -> None:
    """Zip wiki/ + .llm-wiki/ + raw/ into output_zip (skip .index/)."""
    ensure_knowledge_base(paths.root)
    output_zip = Path(output_zip)
    output_zip.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for sub in ("wiki", ".llm-wiki", "raw"):
            src_dir = paths.root / sub
            if not src_dir.exists():
                continue
            for file in src_dir.rglob("*"):
                if not file.is_file():
                    continue
                # Skip LanceDB index directory
                if ".index" in file.parts:
                    continue
                arc = file.relative_to(paths.root)
                zf.write(file, arcname=str(arc))
    _logger.info(f"[export] wrote {output_zip}")