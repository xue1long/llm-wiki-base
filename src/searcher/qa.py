# ruflo-kb/src/searcher/qa.py
from typing import Optional

async def generate_answer(query: str, context: list[dict]) -> Optional[str]:
    """
    基于检索结果生成答案
    TODO: 接入 LLM 服务
    """
    if not context:
        return None

    # 简化实现：返回上下文摘要
    top_result = context[0]
    return f"根据搜索结果：\n\n{top_result.get('content', '')[:200]}..."
