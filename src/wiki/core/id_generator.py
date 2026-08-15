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


# Any character outside the id charset (a-z, 0-9, '-', CJK U+4E00–U+9FFF).
# Everything else — full-width parens （）, book brackets 《》, underscores,
# spaces, uppercase ASCII, Latin Extended — must be normalized away.
_ID_ALLOWED_RE = re.compile(r"[^a-z0-9\u4e00-\u9fff-]")


def normalize_id_chars(slug: str) -> str:
    """Normalize a candidate id/slug to the wiki id charset.

    Rules (wiki-spec id regex):
    - Lowercase ASCII (kebab-case is lowercase only).
    - Any character outside ``[a-z0-9-一-鿿]`` → ``-`` (full-width parens,
      book brackets, underscores, spaces, punctuation...).
    - Collapse ``-`` runs; strip leading/trailing ``-``.

    Examples::

        normalize_id_chars("元素化-（-写作问题-）")  -> "元素化-写作问题"
        normalize_id_chars("大纲示例_7c8873")       -> "大纲示例-7c8873"
        normalize_id_chars("OpenAI-写作")            -> "openai-写作"
        normalize_id_chars("《-俄狄浦斯王-》")        -> "俄狄浦斯王"

    Batch-50 regression: H4 flagged 6 invalid ids — full-width parens in
    LLM-generated ids and underscores inherited from filenames.
    """
    if not slug:
        return ""
    slug = slug.lower()
    slug = _ID_ALLOWED_RE.sub("-", slug)
    return re.sub(r"-{2,}", "-", slug).strip("-")
