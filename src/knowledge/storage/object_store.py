"""Object storage abstraction for raw files and media.

Supports S3-compatible storage plus a local filesystem fallback.
Default: LocalObjectStore (zero extra dependencies).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Key sanitization
# ---------------------------------------------------------------------------

def _sanitize_key(key: str) -> str:
    """Replace path separators to prevent directory traversal.

    Both ``/`` and ``\\`` are replaced with ``_`` so that a key like
    ``a/b\\c`` ends up as ``a_b_c``.
    """
    return key.replace("\\", "_").replace("/", "_")


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class ObjectStore(ABC):
    """Object storage abstraction for raw files and media.

    Supports S3-compatible storage + local filesystem fallback.
    Default: local filesystem (zero extra dependencies).
    """

    @abstractmethod
    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        """Store an object. Returns the storage key/URL."""
        ...

    @abstractmethod
    async def get(self, key: str) -> bytes | None:
        """Retrieve an object. Returns None if not found."""
        ...

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete an object."""
        ...

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Check if an object exists."""
        ...

    @abstractmethod
    def public_url(self, key: str) -> str:
        """Return a public URL for the object (S3: presigned, Local: file://)."""
        ...


# ---------------------------------------------------------------------------
# Local filesystem backend (default)
# ---------------------------------------------------------------------------


class LocalObjectStore(ObjectStore):
    """Local filesystem implementation — default for single-instance deployments.

    Stores objects under ``{base_dir}/objects/{sanitized_key}``.
    """

    def __init__(self, base_dir: Path) -> None:
        self._base = Path(base_dir) / "objects"
        self._base.mkdir(parents=True, exist_ok=True)

    # -- helpers ------------------------------------------------------------

    def _resolve(self, key: str) -> Path:
        """Return the absolute filesystem path for *key*."""
        return self._base / _sanitize_key(key)

    # -- ObjectStore interface ----------------------------------------------

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        """Write *data* to disk. Create parent directories as needed."""
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    async def get(self, key: str) -> bytes | None:
        """Read *data* from disk. Return ``None`` if the file is missing."""
        path = self._resolve(key)
        try:
            return path.read_bytes()
        except FileNotFoundError:
            return None

    async def delete(self, key: str) -> None:
        """Remove the file from disk (no-op if missing)."""
        path = self._resolve(key)
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    async def exists(self, key: str) -> bool:
        """Return ``True`` if the file exists on disk."""
        return self._resolve(key).is_file()

    def public_url(self, key: str) -> str:
        """Return a ``file:///`` URL for the stored object."""
        path = self._resolve(key)
        return path.resolve().as_uri()


# ---------------------------------------------------------------------------
# S3 backend (optional boto3 dependency)
# ---------------------------------------------------------------------------


class S3ObjectStore(ObjectStore):
    """S3-compatible object storage (AWS S3, Cloudflare R2, MinIO).

    Requires ``boto3`` (optional).  Falls back gracefully to a
    ``LocalObjectStore`` when boto3 is unavailable or on transient errors.
    """

    def __init__(
        self,
        endpoint_url: str,
        bucket: str,
        access_key: str = "",
        secret_key: str = "",
        fallback: LocalObjectStore | None = None,
    ) -> None:
        self._endpoint = endpoint_url
        self._bucket = bucket
        self._access_key = access_key
        self._secret_key = secret_key
        self._fallback = fallback
        self._client = None  # lazy init

    # -- helpers ------------------------------------------------------------

    def _ensure_client(self) -> None:
        """Lazy-init the boto3 S3 client.  If boto3 is not installed the
        internal ``_client`` stays ``None`` and every method delegates
        to the fallback store."""
        if self._client is not None:
            return

        try:
            import boto3  # type: ignore[import-untyped]
        except ImportError:
            logger.warning("boto3 not installed — S3ObjectStore will use fallback")
            self._client = None
            return

        try:
            session_kwargs: dict = {}
            if self._access_key:
                session_kwargs["aws_access_key_id"] = self._access_key
            if self._secret_key:
                session_kwargs["aws_secret_access_key"] = self._secret_key

            self._client = boto3.client(
                "s3",
                endpoint_url=self._endpoint,
                **session_kwargs,
            )
        except Exception:
            logger.exception("Failed to create boto3 S3 client — using fallback")
            self._client = None

    def _require_client(self) -> bool:
        """Ensure a client exists; return ``False`` if it could not be created."""
        if self._client is not None:
            return True
        self._ensure_client()
        return self._client is not None

    def _fallback_or_raise(self, method: str) -> LocalObjectStore:
        """Return the fallback store or raise ``RuntimeError``."""
        if self._fallback is not None:
            logger.warning("S3 %s failed — delegating to LocalObjectStore fallback", method)
            return self._fallback
        raise RuntimeError(
            f"S3 {method} failed and no fallback LocalObjectStore configured"
        )

    # -- ObjectStore interface ----------------------------------------------

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        safe_key = _sanitize_key(key)
        if not self._require_client():
            return await self._fallback_or_raise("put").put(key, data, content_type)

        try:
            self._client.put_object(  # type: ignore[union-attr]
                Bucket=self._bucket,
                Key=safe_key,
                Body=data,
                ContentType=content_type,
            )
            return safe_key
        except Exception:
            logger.exception("S3 put_object failed for key=%r", safe_key)
            return await self._fallback_or_raise("put").put(key, data, content_type)

    async def get(self, key: str) -> bytes | None:
        safe_key = _sanitize_key(key)
        if not self._require_client():
            return await self._fallback_or_raise("get").get(key)

        try:
            response = self._client.get_object(  # type: ignore[union-attr]
                Bucket=self._bucket,
                Key=safe_key,
            )
            return response["Body"].read()
        except self._client.exceptions.NoSuchKey:  # type: ignore[union-attr]
            return None
        except Exception:
            logger.exception("S3 get_object failed for key=%r", safe_key)
            return await self._fallback_or_raise("get").get(key)

    async def delete(self, key: str) -> None:
        safe_key = _sanitize_key(key)
        if not self._require_client():
            await self._fallback_or_raise("delete").delete(key)
            return

        try:
            self._client.delete_object(  # type: ignore[union-attr]
                Bucket=self._bucket,
                Key=safe_key,
            )
        except Exception:
            logger.exception("S3 delete_object failed for key=%r", safe_key)
            await self._fallback_or_raise("delete").delete(key)

    async def exists(self, key: str) -> bool:
        safe_key = _sanitize_key(key)
        if not self._require_client():
            return await self._fallback_or_raise("exists").exists(key)

        try:
            self._client.head_object(  # type: ignore[union-attr]
                Bucket=self._bucket,
                Key=safe_key,
            )
            return True
        except Exception:
            return False

    def public_url(self, key: str) -> str:
        """Return the S3 endpoint URL for *key*.

        If a boto3 client is available this generates a presigned URL
        (1-hour expiry); otherwise it builds a static endpoint URL.
        Falls back to the local store URL if configured.
        """
        safe_key = _sanitize_key(key)
        if self._client is not None:
            try:
                return self._client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self._bucket, "Key": safe_key},
                    ExpiresIn=3600,
                )
            except Exception:
                logger.exception("S3 presigned URL failed — using static URL")

        # Delegate to local fallback when S3 client is unavailable
        if self._fallback is not None:
            return self._fallback.public_url(key)

        # Static fallback
        ep = self._endpoint.rstrip("/")
        return f"{ep}/{self._bucket}/{safe_key}"
