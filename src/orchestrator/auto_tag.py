"""UGC carrier auto-tagging."""
from __future__ import annotations

_UGC_TAGS = ("素材/ugc", "可信度/ugc")


def auto_tag_ugc(pages: list, raw_headers: dict[str, str]) -> int:
    """Tag pages derived from UGC-carrier sources in place."""
    from src.wiki.features.lint import _is_ugc_carrier

    carrier_raws = {
        raw for raw, header in (raw_headers or {}).items()
        if _is_ugc_carrier(header)
    }
    if not carrier_raws:
        return 0

    tagged = 0
    for page in pages:
        if getattr(page, "processing_depth", "") == "stub":
            continue
        if not (set(page.sources or []) & carrier_raws):
            continue
        tags = list(page.tags or [])
        changed = False
        for tag in _UGC_TAGS:
            if tag not in tags:
                tags.append(tag)
                changed = True
        if changed:
            page.tags = tags
            tagged += 1
    return tagged
