# ruflo-kb/src/utils/similarity.py
import math


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """计算两个向量的余弦相似度

    Args:
        a: 第一个向量
        b: 第二个向量

    Returns:
        余弦相似度，范围 [0.0, 1.0]。如果向量长度不同或为空，返回 0.0。
    """
    if not a or not b or len(a) != len(b):
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

    # Prefix match: shorter at start of longer
    # Use len(shorter)/len(longer) so a prefix returns a proper ratio
    # (e.g. 'a' vs 'apple' → 1/5 = 0.2, not 1.0). The previous
    # len(shorter)/len(shorter) branch always returned 1.0, hiding the fact
    # that only part of the longer string matched.
    if shorter in longer and longer.startswith(shorter):
        return len(shorter) / len(longer)

    # 简单字符匹配
    match_count = sum(1 for char in shorter if char in longer)
    return match_count / (len(a_lower) + len(b_lower))
