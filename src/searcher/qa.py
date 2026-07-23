# ruflo-kb/src/searcher/qa.py
"""Question-answering module.

The model output may contain ``[N]`` citation markers referring to
source documents. We validate each marker against the actual context
and discard any that are out of range — those are hallucinated
references, not safe to surface to the caller.

The validation rules (per the task-13 brief):
- citation indices are 1-indexed integers in ``[1-9]\\d*`` form
- an index is valid iff ``1 <= index <= len(context)``
- indices outside the valid range are silently dropped
- the LLM output text is rewritten to remove invalid citations
- a debug-level log records how many citations were dropped
"""
import logging
import re
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..llm import LLMProvider

logger = logging.getLogger(__name__)

#: Regex matching a citation marker like ``[12]``. The body must be a
#: positive integer (no leading zero, no negative sign, no decimal).
_CITATION_RE = re.compile(r"\[([1-9]\d*)\]")


def _parse_citation_indices(text: str) -> list[int]:
    """Extract all citation indices from ``text`` in document order.

    Returns a list of unique indices in the order they first appear.
    """
    seen: set[int] = set()
    out: list[int] = []
    for match in _CITATION_RE.finditer(text):
        n = int(match.group(1))
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def validate_citations(text: str, n_context: int) -> list[int]:
    """Return the citation indices from ``text`` that are in range.

    A citation index is valid iff ``1 <= index <= n_context``. Indices
    outside that range (including 0) are dropped.
    """
    if n_context < 0:
        raise ValueError(f"n_context must be >= 0, got {n_context}")
    if not text:
        return []
    return [n for n in _parse_citation_indices(text) if 1 <= n <= n_context]


def strip_invalid_citations(text: str, n_context: int) -> str:
    """Remove citation markers whose index is not in range from ``text``.

    Valid citations are preserved verbatim. A debug log records how many
    markers were dropped.
    """
    if not text:
        return text
    if n_context <= 0:
        # No valid citations possible — strip them all.
        dropped = len(_CITATION_RE.findall(text))
        if dropped:
            logger.debug("citation validation: dropped %d invalid citation(s) (n_context=0)", dropped)
        return _CITATION_RE.sub("", text)

    def _repl(match: re.Match) -> str:
        n = int(match.group(1))
        if 1 <= n <= n_context:
            return match.group(0)
        return ""

    out = _CITATION_RE.sub(_repl, text)
    before = len(_CITATION_RE.findall(text))
    after = len(_CITATION_RE.findall(out))
    dropped = before - after
    if dropped:
        logger.debug(
            "citation validation: dropped %d invalid citation(s) (n_context=%d)",
            dropped, n_context,
        )
    return out


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

    Citations in the model's output are validated: any ``[N]`` whose N
    is outside ``range(1, len(context) + 1)`` is discarded so we do not
    surface hallucinated references to the caller.
    """
    if not context:
        return None

    if not _llm_provider:
        # 简化实现：返回上下文摘要
        top_result = context[0]
        raw = f"根据搜索结果：\n\n{top_result.get('content', '')[:200]}..."
        return strip_invalid_citations(raw, n_context=len(context))

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
        # Validate citations: drop any [N] where N is out of range.
        return strip_invalid_citations(response.content, n_context=len(context))
    except Exception as e:
        # Fallback to simple summary
        top_result = context[0]
        raw = f"根据搜索结果：\n\n{top_result.get('content', '')[:200]}..."
        return strip_invalid_citations(raw, n_context=len(context))


#: Alias matching the task-13 brief interface ``qa.answer(query, context)``.
answer = generate_answer
