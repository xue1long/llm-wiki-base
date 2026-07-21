# ruflo-kb/src/searcher/qa.py
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..llm import LLMProvider

_llm_provider: Optional["LLMProvider"] = None

def set_llm_provider(provider: "LLMProvider") -> None:
    """设置全局 LLM provider"""
    global _llm_provider
    _llm_provider = provider

def get_llm_provider() -> Optional["LLMProvider"]:
    """获取全局 LLM provider"""
    return _llm_provider

async def generate_answer(query: str, context: list[dict]) -> Optional[str]:
    """
    基于检索结果生成答案
    使用 LLM Provider 接入 GPT/Claude
    """
    if not context:
        return None

    if not _llm_provider:
        # 简化实现：返回上下文摘要
        top_result = context[0]
        return f"根据搜索结果：\n\n{top_result.get('content', '')[:200]}..."

    # 构建 prompt
    context_text = "\n\n".join([
        f"【来源 {i+1}】{r.get('content', '')[:500]}"
        for i, r in enumerate(context[:3])
    ])

    prompt = f"""基于以下参考资料回答用户问题。如果资料不足以回答，请说明。

参考资料：
{context_text}

用户问题：{query}

回答："""

    try:
        response = await _llm_provider.complete(
            prompt,
            max_tokens=500,
            temperature=0.7,
        )
        return response.content
    except Exception as e:
        # Fallback to simple summary
        top_result = context[0]
        return f"根据搜索结果：\n\n{top_result.get('content', '')[:200]}..."
