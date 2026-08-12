import hashlib
from pathlib import Path

from src.utils.hashing import sha256_file


def test_sha256_file_empty_file(tmp_path):
    file_path = tmp_path / "empty.bin"
    file_path.write_bytes(b"")

    assert sha256_file(file_path) == hashlib.sha256(b"").hexdigest()


def test_sha256_file_reads_multiple_chunks(tmp_path):
    file_path = tmp_path / "big.bin"
    data = (b"abcdef0123456789" * 5000) + b"tail"
    file_path.write_bytes(data)

    assert sha256_file(file_path, chunk_size=1024) == hashlib.sha256(data).hexdigest()


def test_sha256_file_accepts_path_objects(tmp_path):
    file_path = Path(tmp_path / "note.md")
    file_path.write_text("hello", encoding="utf-8")

    assert sha256_file(file_path) == hashlib.sha256(b"hello").hexdigest()
