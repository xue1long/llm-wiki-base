# ruflo-kb/src/llm/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

@dataclass
class LLMResponse:
    content: str
    model: str
    usage: Optional[dict] = None

@dataclass
class EmbeddingResponse:
    embedding: list[float]
    model: str

class LLMProvider(ABC):
    """LLM Provider 抽象接口"""

    @abstractmethod
    async def complete(self, prompt: str, **kwargs) -> LLMResponse:
        """生成文本补全"""
        pass

    @abstractmethod
    async def embed(self, text: str) -> EmbeddingResponse:
        """生成文本 embedding"""
        pass

    @abstractmethod
    async def chat(self, messages: list[dict], **kwargs) -> LLMResponse:
        """聊天对话"""
        pass

class EmbeddingProvider(ABC):
    """Embedding 专用 Provider"""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[EmbeddingResponse]:
        """批量生成 embedding"""
        pass
