# ruflo-kb/src/llm/openai_provider.py
import os
from typing import Optional
from .base import LLMProvider, EmbeddingProvider, LLMResponse, EmbeddingResponse

class OpenAIProvider(LLMProvider):
    """OpenAI Provider 实现"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        endpoint: Optional[str] = None,
        model: str = "gpt-4",
        embedding_model: str = "text-embedding-3-small",
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.endpoint = endpoint or "https://api.openai.com/v1"
        self.model = model
        self.embedding_model = embedding_model

    async def complete(self, prompt: str, **kwargs) -> LLMResponse:
        """使用 OpenAI 完成文本"""
        try:
            import httpx
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            data = {
                "model": kwargs.get("model", self.model),
                "prompt": prompt,
                "max_tokens": kwargs.get("max_tokens", 1000),
                "temperature": kwargs.get("temperature", 0.7),
            }
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.endpoint}/completions",
                    headers=headers,
                    json=data,
                    timeout=30.0,
                )
                response.raise_for_status()
                result = response.json()

            return LLMResponse(
                content=result["choices"][0]["text"],
                model=result.get("model", self.model),
                usage=result.get("usage"),
            )
        except Exception as e:
            raise RuntimeError(f"OpenAI complete failed: {e}")

    async def embed(self, text: str) -> EmbeddingResponse:
        """使用 OpenAI 生成 embedding"""
        try:
            import httpx
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            data = {
                "model": self.embedding_model,
                "input": text,
            }
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.endpoint}/embeddings",
                    headers=headers,
                    json=data,
                    timeout=30.0,
                )
                response.raise_for_status()
                result = response.json()

            return EmbeddingResponse(
                embedding=result["data"][0]["embedding"],
                model=self.embedding_model,
            )
        except Exception as e:
            raise RuntimeError(f"OpenAI embed failed: {e}")

    async def chat(self, messages: list[dict], **kwargs) -> LLMResponse:
        """使用 OpenAI 进行聊天"""
        try:
            import httpx
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            data = {
                "model": kwargs.get("model", self.model),
                "messages": messages,
                "max_tokens": kwargs.get("max_tokens", 1000),
                "temperature": kwargs.get("temperature", 0.7),
            }
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.endpoint}/chat/completions",
                    headers=headers,
                    json=data,
                    timeout=30.0,
                )
                response.raise_for_status()
                result = response.json()

            return LLMResponse(
                content=result["choices"][0]["message"]["content"],
                model=result.get("model", self.model),
                usage=result.get("usage"),
            )
        except Exception as e:
            raise RuntimeError(f"OpenAI chat failed: {e}")

class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI 专用 Embedding Provider"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        endpoint: Optional[str] = None,
        model: str = "text-embedding-3-small",
        dimension: int = 1536,
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.endpoint = endpoint or "https://api.openai.com/v1"
        self.model = model
        self.dimension = dimension

    async def embed(self, texts: list[str]) -> list[EmbeddingResponse]:
        """批量生成 embedding"""
        try:
            import httpx
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            data = {
                "model": self.model,
                "input": texts,
            }
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.endpoint}/embeddings",
                    headers=headers,
                    json=data,
                    timeout=60.0,
                )
                response.raise_for_status()
                result = response.json()

            return [
                EmbeddingResponse(
                    embedding=item["embedding"],
                    model=self.model,
                )
                for item in result["data"]
            ]
        except Exception as e:
            raise RuntimeError(f"OpenAI embedding failed: {e}")
