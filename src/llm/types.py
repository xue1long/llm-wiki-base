"""LLM provider type definitions."""
from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class ModelInfo:
    name: str
    type: str = "chat"  # "chat" | "embedding"
    context_window: int = 8192
    parameters: dict = field(default_factory=dict)


@dataclass
class ProviderConfig:
    name: str
    type: str  # "openai" | "anthropic" | "ollama" | "openai-compatible"
    base_url: str = ""
    api_key: str = ""
    models: dict[str, ModelInfo] = field(default_factory=dict)
    default_chat_model: str = ""
    default_embedding_model: str = ""
    timeout_seconds: int = 60
    extra_headers: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.type,
            "base_url": self.base_url,
            "api_key": self.api_key,
            "models": {k: asdict(v) for k, v in self.models.items()},
            "default_chat_model": self.default_chat_model,
            "default_embedding_model": self.default_embedding_model,
            "timeout_seconds": self.timeout_seconds,
            "extra_headers": self.extra_headers,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProviderConfig":
        return cls(
            name=d["name"],
            type=d["type"],
            base_url=d.get("base_url", ""),
            api_key=d.get("api_key", ""),
            models={
                k: ModelInfo(**{k2: v2 for k2, v2 in v.items() if k2 in {"name", "type", "context_window", "parameters"}})
                for k, v in d.get("models", {}).items()
            },
            default_chat_model=d.get("default_chat_model", ""),
            default_embedding_model=d.get("default_embedding_model", ""),
            timeout_seconds=d.get("timeout_seconds", 60),
            extra_headers=d.get("extra_headers", {}),
        )
