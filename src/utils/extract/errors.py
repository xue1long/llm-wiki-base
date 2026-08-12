from __future__ import annotations


def looks_like_encryption_error(exc: BaseException) -> bool:
    name = type(exc).__name__
    message = str(exc).lower()
    return name in ("Unknown", "PyCryptodomeWarning") or any(
        token in message for token in ("decrypt", "password", "encrypted", "not been decrypted")
    )
