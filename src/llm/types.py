"""LLM provider type definitions."""
from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class ModelInfo:
    name: str
    type: str = "chat"  # "chat" | "embedding"
    context_window: int = 8192
    parameters: dict = field(default_factory=dict)


def _mask_api_key(api_key: str) -> str:
    """Mask an API key for safe display.

    Uses the "***" + last-4 convention (matching AWS / Stripe). Fallback
    to plain "***" when the key is shorter than 5 chars so we never
    leak the full key (a 4-char key would be equal to its own last 4).
    Empty keys are returned as-is (nothing to mask).
    """
    if not api_key:
        return ""
    if len(api_key) < 5:
        return "***"
    return "***" + api_key[-4:]


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

    def to_dict(self, redact: bool = False) -> dict:
        """Serialize to dict.

        Args:
            redact: When True, ``api_key`` is masked ("***" + last 4 chars,
                or "***" if shorter than 4 chars). Default False preserves
                the full key for internal callers that need to make actual
                API requests — call sites that display the result to a
                user MUST pass ``redact=True``.
        """
        return {
            "name": self.name,
            "type": self.type,
            "base_url": self.base_url,
            "api_key": _mask_api_key(self.api_key) if redact else self.api_key,
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
