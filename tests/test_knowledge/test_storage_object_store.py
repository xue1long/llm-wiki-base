"""Test ObjectStore — local + S3 backend with fallback (Task 5.2)."""
from pathlib import Path

import pytest

from src.knowledge.storage.object_store import (
    ObjectStore,
    LocalObjectStore,
    S3ObjectStore,
    _sanitize_key,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path: Path) -> LocalObjectStore:
    """Fresh LocalObjectStore scoped to a temp directory."""
    return LocalObjectStore(base_dir=tmp_path)


# ---------------------------------------------------------------------------
# Key sanitization
# ---------------------------------------------------------------------------

class TestKeySanitization:
    """Unit tests for _sanitize_key."""

    def test_plain_key_unchanged(self):
        assert _sanitize_key("hello.txt") == "hello.txt"

    def test_forward_slash_replaced(self):
        assert _sanitize_key("a/b/c.txt") == "a_b_c.txt"

    def test_backslash_replaced(self):
        assert _sanitize_key("a\\b\\c.txt") == "a_b_c.txt"

    def test_mixed_slashes_replaced(self):
        assert _sanitize_key("a/b\\c") == "a_b_c"


# ---------------------------------------------------------------------------
# LocalObjectStore
# ---------------------------------------------------------------------------

class TestLocalObjectStore:
    """Tests for LocalObjectStore."""

    # 1. put + get
    async def test_put_and_get(self, store: LocalObjectStore):
        await store.put("hello", b"world")
        assert await store.get("hello") == b"world"

    # 2. exists
    async def test_exists_after_put(self, store: LocalObjectStore):
        await store.put("x", b"data")
        assert await store.exists("x") is True

    async def test_exists_unknown_key(self, store: LocalObjectStore):
        assert await store.exists("nonexistent") is False

    # 3. delete
    async def test_delete_removes_object(self, store: LocalObjectStore):
        await store.put("tmp", b"data")
        await store.delete("tmp")
        assert await store.exists("tmp") is False

    async def test_delete_nonexistent_no_error(self, store: LocalObjectStore):
        """Deleting a key that doesn't exist should not raise."""
        await store.delete("no-such-key")  # no exception

    # 4. get nonexistent
    async def test_get_nonexistent_returns_none(self, store: LocalObjectStore):
        assert await store.get("nope") is None

    # 5. overwrite
    async def test_overwrite_returns_latest(self, store: LocalObjectStore):
        await store.put("key", b"first")
        await store.put("key", b"second")
        assert await store.get("key") == b"second"

    # 6. binary data
    async def test_binary_data_roundtrip(self, store: LocalObjectStore):
        binary = bytes(range(256))  # all byte values 0-255
        await store.put("bin", binary)
        assert await store.get("bin") == binary

    # 7. empty data
    async def test_empty_data(self, store: LocalObjectStore):
        await store.put("empty", b"")
        assert await store.get("empty") == b""

    # 8. large data (1 MB)
    async def test_large_data(self, store: LocalObjectStore):
        data = b"A" * (1024 * 1024)  # 1 MiB
        await store.put("large", data)
        assert await store.get("large") == data

    # 9. key sanitization
    async def test_key_with_slashes_is_sanitized(self, tmp_path):
        store = LocalObjectStore(base_dir=tmp_path)
        await store.put("a/b\\c.txt", b"hello")
        # The sanitized key is used; the object is retrievable via the
        # original (sanitized internally) key.
        assert await store.get("a/b\\c.txt") == b"hello"

    # 10. content_type accepted but ignored
    async def test_content_type_accepted(self, store: LocalObjectStore):
        """Local store accepts content_type without error."""
        result = await store.put("doc", b"{}", content_type="application/json")
        assert result == "doc"

    # 11. public_url
    async def test_public_url_returns_string_with_path(self, store: LocalObjectStore):
        await store.put("pic.png", b"png-data")
        url = store.public_url("pic.png")
        assert isinstance(url, str)
        assert "pic.png" in url
        assert url.startswith("file:///") or url.startswith("file:/")


# ---------------------------------------------------------------------------
# ABC enforcement
# ---------------------------------------------------------------------------

class TestObjectStoreABC:
    """Can't instantiate the abstract base class."""

    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            ObjectStore()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# S3ObjectStore (interface + fallback, no live S3 required)
# ---------------------------------------------------------------------------

class TestS3ObjectStore:
    """Tests for S3ObjectStore interface and fallback behavior."""

    def test_class_exists_and_is_object_store(self):
        """S3ObjectStore is a subclass of ObjectStore."""
        assert issubclass(S3ObjectStore, ObjectStore)

    def test_constructor_accepts_expected_args(self):
        """Constructor accepts endpoint, bucket, and credentials."""
        s3 = S3ObjectStore(
            endpoint_url="https://s3.example.com",
            bucket="my-bucket",
            access_key="AKID",
            secret_key="secret",
        )
        assert s3._endpoint == "https://s3.example.com"
        assert s3._bucket == "my-bucket"

    async def test_fallback_on_put_when_no_boto3(self, tmp_path):
        """When boto3 is unavailable, put falls back to LocalObjectStore."""
        local = LocalObjectStore(base_dir=tmp_path)
        s3 = S3ObjectStore(
            endpoint_url="https://s3.example.com",
            bucket="bucket",
            fallback=local,
        )
        # Force boto3-not-imported path
        s3._client = None

        key = await s3.put("obj.txt", b"fallback-data")
        assert await local.get("obj.txt") == b"fallback-data"
        assert key == "obj.txt"

    async def test_fallback_on_get_when_no_boto3(self, tmp_path):
        """When boto3 is unavailable, get falls back to LocalObjectStore."""
        local = LocalObjectStore(base_dir=tmp_path)
        await local.put("obj.txt", b"existing")
        s3 = S3ObjectStore(
            endpoint_url="https://s3.example.com",
            bucket="bucket",
            fallback=local,
        )
        s3._client = None

        assert await s3.get("obj.txt") == b"existing"
        assert await s3.get("missing") is None

    async def test_fallback_on_delete_when_no_boto3(self, tmp_path):
        """When boto3 is unavailable, delete falls back to LocalObjectStore."""
        local = LocalObjectStore(base_dir=tmp_path)
        await local.put("obj.txt", b"data")
        s3 = S3ObjectStore(
            endpoint_url="https://s3.example.com",
            bucket="bucket",
            fallback=local,
        )
        s3._client = None

        await s3.delete("obj.txt")
        assert await local.exists("obj.txt") is False

    async def test_fallback_on_exists_when_no_boto3(self, tmp_path):
        """When boto3 is unavailable, exists falls back to LocalObjectStore."""
        local = LocalObjectStore(base_dir=tmp_path)
        await local.put("obj.txt", b"data")
        s3 = S3ObjectStore(
            endpoint_url="https://s3.example.com",
            bucket="bucket",
            fallback=local,
        )
        s3._client = None

        assert await s3.exists("obj.txt") is True
        assert await s3.exists("nope") is False

    async def test_no_fallback_raises_on_put(self, tmp_path):
        """Without a fallback and without boto3, put raises RuntimeError."""
        # We need to create a store that we know has no boto3
        s3 = S3ObjectStore(
            endpoint_url="https://s3.example.com",
            bucket="bucket",
            fallback=None,
        )
        # Simulate boto3 import failure
        s3._client = None

        with pytest.raises(RuntimeError, match="fallback"):
            await s3.put("key", b"data")

    def test_public_url_static_fallback(self):
        """public_url returns a static endpoint URL when client is None."""
        s3 = S3ObjectStore(
            endpoint_url="https://s3.example.com",
            bucket="my-bucket",
        )
        s3._client = None

        url = s3.public_url("file.png")
        assert "s3.example.com" in url
        assert "my-bucket" in url
        assert "file.png" in url

    def test_public_url_sanitizes_key(self):
        """public_url sanitizes slashes in the key."""
        s3 = S3ObjectStore(
            endpoint_url="https://s3.example.com",
            bucket="my-bucket",
        )
        s3._client = None

        url = s3.public_url("a/b/c.png")
        assert "a_b_c.png" in url
        assert "/" not in url.split("my-bucket/")[-1]
