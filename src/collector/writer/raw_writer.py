# ruflo-kb/src/collector/writer/raw_writer.py
"""将转换结果写入项目实例的 raw/sources/ 目录。"""
from __future__ import annotations

import re
from pathlib import Path

from ..converter.base import ConvertResult


def write_to_raw(
    result: ConvertResult,
    project_root: Path,
    *,
    filename: str | None = None,
) -> str:
    """将 ConvertResult 写入 <project_root>/raw/sources/。

    Args:
        result:       转换结果
        project_root: 项目根目录
        filename:     可选的文件名覆盖（不含路径）

    Returns:
        项目相对路径，如 "raw/sources/xxx.md"
    """
    raw_dir = project_root / "raw" / "sources"
    raw_dir.mkdir(parents=True, exist_ok=True)

    name = filename or _derive_filename(result)
    dest = raw_dir / name

    # 图片类型：保留原始图片 + 写描述 .md
    if result.source_type == "image" and result.raw_bytes:
        # 写原始图片
        img_ext = result.metadata.get("format", "png")
        img_name = f"{_sanitize_filename(result.title)}.{img_ext}"
        img_dest = raw_dir / img_name
        img_dest.write_bytes(result.raw_bytes)

        # 写描述 .md（如果还没覆盖）
        if dest.suffix != ".md":
            dest = raw_dir / f"{_sanitize_filename(result.title)}.md"

    # 写 Markdown 内容
    dest.write_text(result.content, encoding="utf-8")

    return f"raw/sources/{dest.name}"


def _derive_filename(result: ConvertResult) -> str:
    """根据 ConvertResult 推导文件名。"""
    title = _sanitize_filename(result.title) or "untitled"
    ext = _EXT_MAP.get(result.source_type, ".md")
    return f"{title}{ext}"


def _sanitize_filename(name: str) -> str:
    """清理文件名，移除非法字符。"""
    if not name:
        return "untitled"
    # 移除路径分隔符和非法字符
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', name)
    # 截断到 120 字符
    name = name[:120].strip()
    return name or "untitled"


# source_type → 文件扩展名映射
_EXT_MAP = {
    "pdf": ".md",
    "docx": ".md",
    "xlsx": ".md",
    "xls": ".md",
    "html": ".md",
    "text": ".txt",
    "md": ".md",
    "image": ".md",
    "url": ".md",
}
