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
ID_PATTERN = re.compile(r"^(?:card_[0-9a-f]{13}_[0-9a-f]{8}_[a-z0-9-]+|[a-z0-9-]+)$")


def is_valid_id(s: str) -> bool:
    return bool(ID_PATTERN.match(s))