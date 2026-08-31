"""Evidence-preserving text preprocessing public API."""

from .api import chunk_prompt_blocks, preprocess_source
from .types import NoiseReport, PreprocessResult, PromptBlockView, RuleApplication

__all__ = [
    "NoiseReport",
    "PreprocessResult",
    "PromptBlockView",
    "RuleApplication",
    "preprocess_source",
    "chunk_prompt_blocks",
]
