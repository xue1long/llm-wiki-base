from __future__ import annotations

import re


_WRITING_TERMS = (
    "写作", "小说", "网文", "大纲", "剧情", "人物", "角色", "情节",
    "描写", "教程", "技巧", "方法论", "设定", "对白", "对话", "作者",
    "章节", "开篇", "冲突", "节奏", "悬疑", "打斗", "龙套",
)


def classify_by_rules(source_path: str, source_text: str) -> tuple[str, str] | None:
    """Return (content_type, reason) only for high-confidence writing sources."""
    haystack = f"{source_path}\n{source_text[:4000]}"
    hits = sum(term in haystack for term in _WRITING_TERMS)
    if hits < 2:
        return None
    if any(term in haystack for term in ("大纲", "剧情", "章节", "情节")):
        content_type = "outline"
    elif any(term in haystack for term in ("教程", "技巧", "方法论", "写作")):
        content_type = "tutorial"
    elif any(term in haystack for term in ("人物", "角色", "设定")):
        content_type = "setting"
    elif any(term in haystack for term in ("对话", "对白")):
        content_type = "dialogue"
    else:
        content_type = "material"
    return content_type, f"writing signals matched ({hits})"


def is_obvious_boilerplate(source_text: str) -> bool:
    text = source_text.strip()
    return not text or bool(re.fullmatch(r"(?:登录/注册|帮助中心|飞书云文档|下载)\s*", text))
