# ruflo-kb/src/llm/anthropic_provider.py
import os
from typing import Optional
from .base import LLMProvider, LLMResponse, EmbeddingResponse

class AnthropicProvider(LLMProvider):
    """Anthropic Claude Provider 实现"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        endpoint: Optional[str] = None,
        model: str = "claude-3-sonnet-20240229",
    ):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.endpoint = endpoint or "https://api.anthropic.com/v1"
        self.model = model

    async def complete(self, prompt: str, **kwargs) -> LLMResponse:
        """使用 Claude 完成文本"""
        # Claude 不支持纯补全，使用 chat 代替
        return await self.chat([{"role": "user", "content": prompt}], **kwargs)

    async def embed(self, text: str) -> EmbeddingResponse:
        """Anthropic 暂时不支持 embedding"""
        raise NotImplementedError("Anthropic does not support embeddings API")

    async def chat(self, messages: list[dict], **kwargs) -> LLMResponse:
        """使用 Claude 进行聊天"""
        try:
            import httpx
            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            }
            # 转换消息格式
            anthropic_messages = []
            for msg in messages:
                if msg["role"] == "system":
                    continue  # Claude 使用特殊格式
                anthropic_messages.append({
                    "role": msg["role"],
                    "content": msg["content"],
                })

            data = {
                "model": kwargs.get("model", self.model),
                "messages": anthropic_messages,
                "max_tokens": kwargs.get("max_tokens", 1000),
                "temperature": kwargs.get("temperature", 0.7),
            }
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.endpoint}/messages",
                    headers=headers,
                    json=data,
                    timeout=30.0,
                )
                response.raise_for_status()
                result = response.json()

            return LLMResponse(
                content=result["content"][0]["text"],
                model=result.get("model", self.model),
                usage={
                    "input_tokens": result.get("usage", {}).get("input_tokens"),
                    "output_tokens": result.get("usage", {}).get("output_tokens"),
                },
            )
        except Exception as e:
            raise RuntimeError(f"Anthropic chat failed: {e}")
