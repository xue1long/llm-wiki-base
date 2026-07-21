# ruflo-kb/src/utils/path.py
import os

def normalize_path(p: str) -> str:
    """跨平台路径标准化（Windows 反斜杠转正斜杠）"""
    return p.replace("\\", "/")
