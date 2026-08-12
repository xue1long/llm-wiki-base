"""Export wiki to a portable ZIP archive (no .index/lancedb/)."""
import logging
import hashlib
import json
import time
import zipfile
from pathlib import Path

from ..storage.ensure import ensure_knowledge_base
from ..core.paths import WikiPaths
from ...lib.write_hooks import safe_write


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
    _write_export_log(paths, output_zip)
    _logger.info(f"[export] wrote {output_zip}")


def _write_export_log(paths: WikiPaths, output_zip: Path) -> None:
    """Record one compact audit event without putting logs in the archive."""
    wiki_files = [
        p for p in paths.wiki.rglob("*.md")
        if p.name not in {"index.md", "log.md"}
    ] if paths.wiki.exists() else []
    schema_path = paths.root / "schema.md"
    taxonomy_path = paths.root / "taxonomy.md"

    def digest(path: Path) -> str | None:
        if not path.is_file():
            return None
        return hashlib.sha256(path.read_bytes()).hexdigest()[:12]

    record = {
        "exported_at": int(time.time() * 1000),
        "output": str(Path(output_zip)),
        "page_count": len(wiki_files),
        "schema_version": digest(schema_path),
        "taxonomy_version": digest(taxonomy_path),
    }
    log_path = paths.index / "export_log.jsonl"
    previous = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    safe_write(log_path, previous + json.dumps(record, ensure_ascii=False) + "\n")
