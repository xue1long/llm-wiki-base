# ruflo-kb/src/pipeline/processor.py
import re


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
