"""UUID v7 + slug page ID generator."""
import re
import secrets
import time


def generate_page_id(slug: str) -> str:
    """26-char: card_<13hex_millis>_<8hex_random>_<slug>"""
    millis = int(time.time() * 1000) & 0xFFFFFFFFFFFFF  # 13 hex
    rand = secrets.token_hex(4)                         # 8 hex
    return f"card_{millis:013x}_{rand}_{slug}"


# Accepts both UUID v7 (card_<13hex>_<8hex>_<slug>) and legacy pure slug
# After the 2026-07-26 CJK cut-over, slugs may include characters in
# the CJK Unified Ideographs basic block (U+4E00–U+9FFF) in addition to
# ASCII kebab-case.
#
# Two alternatives:
#   1. ``card_<13hex>_<8hex>_<slug>`` — UUIDv7 format. ``_`` literals
#      appear as separators; the slug segment accepts CJK + ASCII
#      kebab-case.
#   2. ``<slug>`` — pure kebab-case (no underscores; CJK allowed).
#
# The two alternatives' char classes are slightly different: alt 1
# must allow ``_`` because the UUIDv7 format uses it as a separator,
# but alt 2 (pure-slug form) deliberately excludes ``_`` because
# kebab-case uses ``-`` instead. Without this asymmetry, the
# alternative-2 path would over-accept strings with underscores
# that should have been UUIDv7 but failed the hex check.
ID_PATTERN = re.compile(
    r"^(?:card_[0-9a-f]{13}_[0-9a-f]{8}_[a-z0-9-一-鿿]+|[a-z0-9-一-鿿]+)$"
)


def is_valid_id(s: str) -> bool:
    return bool(ID_PATTERN.match(s))
