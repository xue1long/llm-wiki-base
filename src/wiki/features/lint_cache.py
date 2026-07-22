"""Cache LLM lint results in .index/lint_cache/."""
import hashlib
import json
import time
from pathlib import Path


CACHE_DIR = ".index/lint_cache"
DEFAULT_TTL = 86400  # 24h


def cache_key(prompt_version: str, wiki_summaries: list[str], index_version: int) -> str:
    h = hashlib.sha256()
    h.update(f"{prompt_version}:{index_version}:".encode())
    for s in sorted(wiki_summaries):
        h.update(s.encode())
    return h.hexdigest()


def get(key: str, cache_dir: Path) -> dict | None:
    path = cache_dir / f"{key}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if int(time.time()) * 1000 > data.get("expires_at", 0):
        return None
    return data


def put(key: str, findings: list, cache_dir: Path, ttl: int = DEFAULT_TTL) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "key": key,
        "created_at": int(time.time()) * 1000,
        "expires_at": int(time.time()) * 1000 + ttl * 1000,
        "findings": findings,
    }
    (cache_dir / f"{key}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def invalidate_all(cache_dir: Path) -> int:
    """Delete all cache entries. Returns count."""
    if not cache_dir.exists():
        return 0
    count = 0
    for f in cache_dir.glob("*.json"):
        f.unlink()
        count += 1
    return count
