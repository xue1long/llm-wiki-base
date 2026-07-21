# ruflo-kb/src/utils/similarity.py
import math

def cosine_similarity(a: list[float], b: list[float]) -> float:
    """计算两个向量的余弦相似度"""
    if len(a) != len(b):
        return 0.0

    dot_product = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot_product / (norm_a * norm_b)

def string_similarity(a: str, b: str) -> float:
    """计算两个字符串的相似度 (0-1)"""
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0

    a_lower = a.lower()
    b_lower = b.lower()

    if a_lower == b_lower:
        return 1.0

    longer = a_lower if len(a_lower) > len(b_lower) else b_lower
    shorter = b_lower if len(a_lower) > len(b_lower) else a_lower

    if longer in shorter:
        return len(shorter) / len(longer)

    # Prefix match: shorter at start of longer
    if shorter in longer and longer.startswith(shorter):
        return len(shorter) / len(shorter)  # 1.0 * len ratio = 1.0 * shorter/shorter

    # 简单字符匹配
    match_count = sum(1 for char in shorter if char in longer)
    return match_count / (len(a_lower) + len(b_lower))
