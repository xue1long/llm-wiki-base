# ruflo-kb/src/pipeline/processor.py
import re
import yaml
import logging
from pathlib import Path
from datetime import datetime

from ..events.event_bus import event_bus
from ..events.events import EventName, ProcessorDonePayload
from ..utils.text import trim_text, chunk_markdown

logger = logging.getLogger(__name__)

def calculate_quality_metrics(content: str) -> dict:
    """
    计算质量指标（软规则）
    返回: {quality_score, ad_ratio, text_density, fluency_score}
    """
    # 广告比例 (简化检测)
    ad_patterns = [
        r"广告", r"推广", r"Sponsored",
        r"width:\s*\d+px", r"data-ad", r"google-ad",
    ]
    ad_matches = sum(len(re.findall(p, content, re.IGNORECASE)) for p in ad_patterns)
    ad_ratio = min(ad_matches / max(len(content), 1) * 10, 1.0)

    # 文本密度
    meaningful_chars = len(re.sub(r"\s", "", content))
    text_density = meaningful_chars / max(len(content), 1)

    # 语言流畅度 (简化: 检查句子完整性)
    sentences = re.split(r"[.!?。！？]+", content)
    complete_sentences = sum(1 for s in sentences if len(s.strip()) > 5)
    fluency_score = complete_sentences / max(len(sentences), 1)

    # 综合质量分
    quality_score = (1 - ad_ratio) * 0.4 + text_density * 0.3 + fluency_score * 0.3
    quality_score = max(0.0, min(1.0, quality_score))

    return {
        "quality_score": round(quality_score, 2),
        "ad_ratio": round(ad_ratio, 3),
        "text_density": round(text_density, 2),
        "fluency_score": round(fluency_score, 2),
    }

async def process(task_id: str, raw_path: str, content: str) -> ProcessorDonePayload:
    """处理内容：清洗 + 摘要 + 标签 + 质量评分"""
    # 1. 清洗
    cleaned = trim_text(content)

    # 2. 生成摘要
    summary = cleaned[:200] + ("..." if len(cleaned) > 200 else "")

    # 3. 简单标签提取
    words = re.findall(r"\b[a-z]{4,}\b", cleaned.lower())
    word_freq = {}
    for w in words:
        word_freq[w] = word_freq.get(w, 0) + 1
    tags = sorted(word_freq.keys(), key=word_freq.get, reverse=True)[:5]

    # 4. 计算质量指标
    metrics = calculate_quality_metrics(cleaned)

    # 5. 生成结构化笔记
    title = Path(raw_path).stem
    processed_at = int(datetime.now().timestamp())

    frontmatter = {
        "title": title,
        "source": raw_path,
        "tags": tags,
        "quality_score": metrics["quality_score"],
        "ad_ratio": metrics["ad_ratio"],
        "text_density": metrics["text_density"],
        "fluency_score": metrics["fluency_score"],
        "processed_at": datetime.fromtimestamp(processed_at).isoformat(),
    }

    note_content = f"""---
{yaml.dump(frontmatter, allow_unicode=True, sort_keys=False)}---

# {title}

## 摘要
{summary}

## 内容
{cleaned}
"""

    # 6. 保存到 Notes
    notes_dir = Path("Notes")
    notes_dir.mkdir(exist_ok=True)
    note_path = notes_dir / f"{task_id}.md"
    note_path.write_text(note_content, encoding="utf-8")

    payload = ProcessorDonePayload(
        task_id=task_id,
        note_path=str(note_path),
        quality_score=metrics["quality_score"],
        ad_ratio=metrics["ad_ratio"],
        text_density=metrics["text_density"],
        fluency_score=metrics["fluency_score"],
    )

    event_bus.emit(EventName.PROCESSOR_DONE, payload)
    return payload
