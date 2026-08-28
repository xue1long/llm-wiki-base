"""Read-only adapter from the existing Collector converters."""

from __future__ import annotations

from pathlib import Path

from src.collector.collector import Collector
from src.kc.compiler.normalize import CanonicalDocument, normalize_text


def decode_text_bytes(content: bytes) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("gb18030")


def _clean_transcript(text: str) -> str:
    lines = []
    for line in text.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if not stripped or stripped.upper() == "WEBVTT" or stripped.isdigit() or " --> " in stripped:
            continue
        lines.append(stripped)
    return "\n".join(lines)


class LegacyCollector:
    """Reuse legacy conversion without invoking its raw writer."""

    def __init__(self, project_root: Path | str = ".") -> None:
        self._collector = Collector(Path(project_root))

    async def collect(self, source: str | Path, *, content: bytes | None = None) -> CanonicalDocument:
        suffix = Path(str(source)).suffix.lower()
        if content is None and suffix in {".txt", ".md", ".markdown", ".text"}:
            content = Path(str(source)).read_bytes()
        if content is not None and suffix in {".srt", ".vtt"}:
            text = _clean_transcript(decode_text_bytes(content))
            if not text.strip():
                raise ValueError(f"empty transcript: {source}")
            return normalize_text(text, source=str(source))
        if content is not None and suffix in {".txt", ".md", ".markdown", ".text"}:
            text = decode_text_bytes(content)
            if suffix in {".txt", ".text"}:
                title = next((line.strip() for line in text.splitlines() if line.strip()), Path(str(source)).stem)
                text = f"# {title}\n\n{text}"
            return normalize_text(text, source=str(source))
        converter = self._collector._find_converter(source)
        if converter is None:
            raise ValueError(f"unsupported source: {source}")
        if content is not None and hasattr(converter, "_dispatch"):
            converted = await converter._dispatch(str(source), content, "text/html")
        else:
            converted = await converter.convert(source, content=content)
        if not converted.content.strip():
            raise ValueError(f"empty source: {source}")
        return normalize_text(converted.content, source=str(source))
