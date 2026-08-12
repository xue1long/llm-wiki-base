"""Duplicate-entity detection with 3-way matching.

Detection passes:
1. Slug normalization — slugify titles, exact match → high confidence (auto-merge)
2. Title edit distance — SequenceMatcher ratio >= 0.85 → high confidence (auto-merge)
3. Vector similarity — cosine >= 0.92 via LanceDB → medium confidence (reviews queue)
"""
import logging
from difflib import SequenceMatcher

from ..core.paths import WikiPaths
from ..storage.page_writer import read_page
from ...utils.slugify import slugify
from ...utils.similarity import cosine_similarity


_logger = logging.getLogger(__name__)

TITLE_SIMILARITY_THRESHOLD = 0.85
VECTOR_SIMILARITY_THRESHOLD = 0.92


def _title_similarity(a: str, b: str) -> float:
    """Return 0.0–1.0 similarity between two titles."""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.strip().lower(), b.strip().lower()).ratio()


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two equal-length vectors."""
    return cosine_similarity(a, b)


def find_duplicates(paths: WikiPaths, provider=None) -> list[tuple[str, str]]:
    """Return (slug_a, slug_b) pairs for high-confidence auto-merge candidates.

    Pass 1 — slug normalization: slugify both titles, compare for exact match.
    Pass 2 — title edit distance: SequenceMatcher ratio >= 0.85.
    """
    entity_files = list(paths.wiki_entities.glob("*.md"))
    if len(entity_files) < 2:
        return []

    pages: list[tuple[str, object]] = []
    for f in entity_files:
        try:
            page = read_page(f)
            pages.append((f.stem, page))
        except Exception:
            _logger.debug("[dedup] Failed to read %s", f, exc_info=True)

    if len(pages) < 2:
        return []

    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for i in range(len(pages)):
        slug_a, page_a = pages[i]
        title_a = page_a.title or slug_a                   # type: ignore[union-attr]
        slug_a_norm = slugify(title_a)

        for j in range(i + 1, len(pages)):
            slug_b, page_b = pages[j]
            title_b = page_b.title or slug_b               # type: ignore[union-attr]
            slug_b_norm = slugify(title_b)

            # Pass 1: slug match
            if slug_a_norm and slug_b_norm and slug_a_norm == slug_b_norm:
                pair = (slug_a, slug_b) if slug_a < slug_b else (slug_b, slug_a)
                if pair not in seen:
                    seen.add(pair)
                    pairs.append(pair)
                continue

            # Pass 2: title edit distance
            if _title_similarity(title_a, title_b) >= TITLE_SIMILARITY_THRESHOLD:
                pair = (slug_a, slug_b) if slug_a < slug_b else (slug_b, slug_a)
                if pair not in seen:
                    seen.add(pair)
                    pairs.append(pair)

    _logger.info("[dedup] %d entities, %d high-confidence pairs", len(pages), len(pairs))
    return pairs


def find_near_duplicates(paths: WikiPaths, provider=None) -> list[tuple[str, str, float]]:
    """Return (slug_a, slug_b, confidence) for medium-confidence near-duplicates.

    Uses LanceDB vector similarity (cosine >= 0.92). Best-effort — returns []
    if the vector store is unavailable or contains no entity embeddings.

    Results are intended for the reviews queue, not auto-merge.
    """
    entity_files = list(paths.wiki_entities.glob("*.md"))
    if len(entity_files) < 2:
        return []

    entity_slugs = {f.stem for f in entity_files}
    slug_embeddings = _get_entity_embeddings(paths, entity_slugs)
    if len(slug_embeddings) < 2:
        return []

    slugs = list(slug_embeddings.keys())
    results: list[tuple[str, str, float]] = []
    seen: set[tuple[str, str]] = set()

    for i in range(len(slugs)):
        sa = slugs[i]
        va = slug_embeddings[sa]
        for j in range(i + 1, len(slugs)):
            sb = slugs[j]
            vb = slug_embeddings[sb]
            sim = _cosine_similarity(va, vb)
            if sim >= VECTOR_SIMILARITY_THRESHOLD:
                pair = (sa, sb) if sa < sb else (sb, sa)
                if pair not in seen:
                    seen.add(pair)
                    results.append((pair[0], pair[1], round(sim, 4)))

    _logger.info("[dedup] vector pass: %d near-duplicate pairs", len(results))
    return results


def _get_entity_embeddings(paths: WikiPaths, entity_slugs: set[str]) -> dict[str, list[float]]:
    """Extract one embedding per entity slug from the LanceDB vector store.

    Best-effort — returns {} if the store is unavailable or unreadable.
    """
    try:
        from ...vector.store import get_table
        table = get_table(paths)
        lance_dataset = table.to_lance()
        arrow_table = lance_dataset.to_table()
    except Exception:
        _logger.debug("[dedup] Cannot read vector table, skipping vector pass")
        return {}

    slug_embs: dict[str, list[float]] = {}
    try:
        task_id_col = arrow_table.column("task_id")
        emb_col = arrow_table.column("embedding")
        for i in range(arrow_table.num_rows):
            tid = task_id_col[i].as_py()
            if tid in entity_slugs and tid not in slug_embs:
                emb = emb_col[i].as_py()
                if emb:
                    slug_embs[tid] = emb
    except Exception:
        _logger.debug("[dedup] Error reading vector columns", exc_info=True)
        return {}

    return slug_embs
