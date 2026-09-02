"""Central configuration module — all env-var-driven configuration coalesces here.

Each :class:`Settings` instantiation reads fresh from ``os.environ`` (no
``@lru_cache``), so hot-switch env vars (``RUFLO_PIPELINE_MODE``,
``RUFLO_SHADOW_MODE``) that are written at runtime by
:mod:`src.pipeline.shadow` work correctly.

Usage::

    from src.config import settings

    s = settings()
    if s.max_source_chars > 10000:
        ...

The :func:`settings()` factory is the recommended entry point.
"""

from __future__ import annotations

from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Read configuration from environment variables.

    NOT cached: each instantiation reads fresh from ``os.environ``.
    Hot-switch variables (``RUFLO_PIPELINE_MODE``, ``RUFLO_SHADOW_MODE``)
    that are written at runtime by :mod:`src.pipeline.shadow` use direct
    ``os.environ`` access on the write path — this class provides only a
    read view.

    Field names are explicit ``validation_alias``-mapped to the real env
    var names so ``pydantic-settings`` resolves them case-insensitively and
    never falls back to the (unrelated) lowercase field name.
    """

    # ── CLI ──
    config_dir: str = Field(default="", validation_alias="RUFLO_CONFIG_DIR")

    # ── LLM providers ──
    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")
    anthropic_api_key: str = Field(default="", validation_alias="ANTHROPIC_API_KEY")
    llm_provider: str = Field(default="", validation_alias="RUFLO_LLM_PROVIDER")

    # ── Pipeline behavior ──
    max_source_chars: int = Field(default=16000, validation_alias="RUFLO_MAX_SOURCE_CHARS")
    sanitizer_skip_llm: bool = Field(default=False, validation_alias="RUFLO_SANITIZER_SKIP_LLM")
    json_debug_dir: str = Field(default="", validation_alias="RUFLO_JSON_DEBUG_DIR")
    taxonomy_validation: str = Field(default="warn", validation_alias="RUFLO_TAXONOMY_VALIDATION")

    # ── Resource limits (R2) ──
    # Max bytes for a single ingested source (upload / URL / folder file).
    # Default 50 MiB; enforced at the HTTP upload route AND the unified
    # Collector source-read layer so no ingestion entry can bypass it.
    max_upload_bytes: int = Field(
        default=50 * 1024 * 1024,
        validation_alias="RUFLO_MAX_UPLOAD_BYTES",
    )

    # ── External services ──
    tavily_api_key: str = Field(default="", validation_alias="TAVILY_API_KEY")

    # ── Editor / interactive ──
    editor: str = Field(default="", validation_alias="EDITOR")
    visual: str = Field(default="", validation_alias="VISUAL")
    noninteractive: bool = Field(default=False, validation_alias="RUFO_NONINTERACTIVE")

    # ── Pipeline hot-switch (read-only) — write path stays in shadow.py ──
    pipeline_mode: str = Field(default="", validation_alias="RUFLO_PIPELINE_MODE")
    shadow_mode: str = Field(default="", validation_alias="RUFLO_SHADOW_MODE")
    evidence_contract: str = Field(default="v1", validation_alias="RUFLO_EVIDENCE_CONTRACT")

    # ── Storage backend (experimental — 第二批，暂不迁移调用点) ──
    storage_backend: str = Field(default="filesystem", validation_alias="STORAGE_BACKEND")
    database_url: str = Field(default="", validation_alias="DATABASE_URL")
    s3_endpoint_url: str = Field(default="", validation_alias="S3_ENDPOINT_URL")
    s3_bucket: str = Field(default="", validation_alias="S3_BUCKET")
    s3_access_key: str = Field(default="", validation_alias="S3_ACCESS_KEY")
    s3_secret_key: str = Field(default="", validation_alias="S3_SECRET_KEY")

    model_config = {"env_prefix": "", "case_sensitive": False}


def settings() -> Settings:
    """Return a fresh :class:`Settings` instance (no caching).

    Call this function rather than ``Settings()`` directly for a consistent
    entry point — swap to a cached variant later without changing callers.
    """
    return Settings()


__all__ = ["Settings", "settings"]
