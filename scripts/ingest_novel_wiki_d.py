#!/usr/bin/env python3
"""
Standalone ingestion script for the novel-wiki knowledge base.

Ingests all raw source documents in knowledge/novel-wiki/raw/sources/
through the ruflo-kb pipeline (Collector -> Analyzer -> Generator -> wiki).

Usage:
    python scripts/ingest_novel_wiki_d.py            # ingest all files
    python scripts/ingest_novel_wiki_d.py 1         # ingest file #1 only
    python scripts/ingest_novel_wiki_d.py 1 5       # ingest files #1 through #5

Key design choices:
  - Bypasses the HTTP server; calls src.pipeline.run_ingest() directly.
  - Uses the project's default LLM provider (MiniMax) via _get_provider().
  - Sequential ingestion with inter-file delays to avoid 429 rate limits.
  - Exponential backoff retry on 429 / transient errors.
  - WikiPaths resolved explicitly to knowledge/novel-wiki (D: location),
    NOT via the global registry (which may still point to the old E: path).
"""
import asyncio
import sys
import time
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# 1. Bootstrap: set CWD to the ruflo-kb project root, load .env explicitly.
#    NOTE: src/__init__.py does NOT call load_dotenv() — we must do it here.
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent  # .../ruflo-kb
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env (python-dotenv). Also try ~/.config/ruflo-kb/env if it exists.
from dotenv import load_dotenv

_env_file = PROJECT_ROOT / ".env"
if _env_file.exists():
    load_dotenv(_env_file, override=False)
    print(f"[env] loaded {_env_file}", flush=True)
else:
    print(f"[env] WARNING: .env not found at {_env_file}", flush=True)

_user_env = Path.home() / ".config" / "ruflo-kb" / "env"
if _user_env.exists():
    load_dotenv(_user_env, override=False)
    print(f"[env] loaded {_user_env}", flush=True)

# The novel-wiki KB root (contains raw/sources, wiki/, .llm-wiki/, etc.)
KB_ROOT = PROJECT_ROOT / "knowledge" / "novel-wiki"
RAW_SOURCES = KB_ROOT / "raw" / "sources"

# ---------------------------------------------------------------------------
# 2. Import pipeline components
# ---------------------------------------------------------------------------
from src.wiki.core.paths import WikiPaths
from src.pipeline import run_ingest, _get_provider
from src.llm.types import ProviderConfig


def _make_minimax_provider_directly():
    """Create a MiniMax OpenAI-compatible provider directly from env vars.

    Fallback for when the global registry doesn't have minimax registered
    or _env_var_for_provider doesn't map 'minimax' -> MINIMAX_API_KEY.
    """
    from src.llm.openai_provider import OpenAIProvider
    api_key = os.environ.get("MINIMAX_API_KEY", "")
    if not api_key:
        # Diagnostic: show what env vars ARE set
        minimax_vars = {k: v[:12] + "..." for k, v in os.environ.items()
                        if "MINIMAX" in k.upper()}
        raise RuntimeError(
            f"MINIMAX_API_KEY not set in environment / .env\n"
            f"  MINIMAX_* vars found: {minimax_vars or '(none)'}\n"
            f"  .env path: {PROJECT_ROOT / '.env'}\n"
            f"  .env exists: {(PROJECT_ROOT / '.env').exists()}"
        )
    print(f"[provider] MINIMAX_API_KEY found: {api_key[:8]}...{api_key[-4:]}", flush=True)
    cfg = ProviderConfig(
        name="minimax",
        type="openai",
        base_url=os.environ.get("MINIMAX_BASE_URL", "https://api.minimax.chat/v1"),
        api_key=api_key,
        default_chat_model=os.environ.get("MINIMAX_CHAT_MODEL", "MiniMax-Text-01"),
        timeout_seconds=180,
    )
    return OpenAIProvider(cfg)


def get_provider_robust():
    """Get LLM provider: prefer MiniMax (per project intent), fall back to registry.

    The global registry default is Anthropic which 403s in this environment,
    so we explicitly prefer MiniMax (configured via MINIMAX_API_KEY in .env).
    """
    # Strategy 1: prefer MiniMax from .env (this is the intended provider)
    api_key = os.environ.get("MINIMAX_API_KEY", "")
    if api_key:
        print("[provider] using MiniMax from .env (preferred)", flush=True)
        return _make_minimax_provider_directly()
    print("[provider] MINIMAX_API_KEY not set, falling back to registry default",
          flush=True)
    # Strategy 2: fall back to registry-configured default provider
    try:
        return _get_provider()
    except Exception as e:
        print(f"[provider] _get_provider() failed: {e}", flush=True)
        raise

# ---------------------------------------------------------------------------
# 3. Discover all raw source files
# ---------------------------------------------------------------------------
SUPPORTED_EXT = {".md", ".txt", ".pdf", ".docx", ".xlsx", ".html", ".htm"}
all_files = sorted(
    f for f in RAW_SOURCES.iterdir()
    if f.is_file() and f.suffix.lower() in SUPPORTED_EXT
)

# ---------------------------------------------------------------------------
# 4. Ingestion with rate-limit-aware retry
# ---------------------------------------------------------------------------
INTER_FILE_DELAY = 25  # seconds between files (avoid MiniMax 429)
MAX_RETRIES = 4
INITIAL_BACKOFF = 30  # seconds, doubles each retry


def is_rate_limit_error(exc: Exception) -> bool:
    """Check if an exception is a 429 rate-limit error."""
    msg = str(exc).lower()
    return "429" in msg or "too many requests" in msg or "rate" in msg


async def ingest_one(paths: WikiPaths, provider, sp: Path, text: str,
                     task_id: str) -> list:
    """Ingest a single file with retry on rate-limit errors."""
    backoff = INITIAL_BACKOFF
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            pages = await run_ingest(
                paths=paths,
                source_path=sp,
                source_text=text,
                provider=provider,
                task_id=task_id,
            )
            return pages
        except Exception as e:
            if is_rate_limit_error(e) and attempt < MAX_RETRIES:
                print(f"   [429 retry {attempt}/{MAX_RETRIES}] "
                      f"waiting {backoff}s...", flush=True)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 180)  # cap at 3 min
                continue
            # Non-retryable or exhausted retries
            raise
    raise RuntimeError(f"exhausted retries for {task_id}")


async def main():
    # --- Parse file range ---
    if len(sys.argv) == 1:
        targets = all_files
    elif len(sys.argv) == 2:
        targets = [all_files[int(sys.argv[1]) - 1]]
    else:
        start, end = int(sys.argv[1]), int(sys.argv[2])
        targets = all_files[start - 1:end]

    print(f"=== novel-wiki ingestion ===", flush=True)
    print(f"KB root:    {KB_ROOT}", flush=True)
    print(f"Raw dir:    {RAW_SOURCES}", flush=True)
    print(f"Files found: {len(all_files)}", flush=True)
    print(f"Targeting:  {len(targets)} file(s)", flush=True)
    for i, f in enumerate(targets, 1):
        print(f"  [{i}] {f.name}", flush=True)
    print(flush=True)

    # --- Resolve WikiPaths explicitly (not via registry) ---
    paths = WikiPaths(KB_ROOT)
    print(f"WikiPaths.root = {paths.root}", flush=True)
    print(f"  wiki        -> {paths.wiki}", flush=True)
    print(f"  raw_sources -> {paths.raw_sources}", flush=True)
    print(f"  wiki exists: {paths.wiki.exists()}", flush=True)
    print(f"  raw exists:  {paths.raw_sources.exists()}", flush=True)
    print(flush=True)

    # --- Get LLM provider (prefer MiniMax, registry fallback) ---
    provider = get_provider_robust()
    print(f"Provider: {type(provider).__name__}", flush=True)
    # Print model info if available
    model = getattr(provider, "model", None) or getattr(provider, "_model", None)
    if model:
        print(f"Model:   {model}", flush=True)
    print(flush=True)

    # --- Ingest each file ---
    results = []
    total = len(targets)
    for idx, sp in enumerate(targets, 1):
        fname = sp.name
        text = sp.read_text(encoding="utf-8")
        tid = f"manual-d-{idx}-{int(time.time())}"
        t0 = time.time()
        print(f"--- [{idx}/{total}] {fname} ({len(text)} chars) ---", flush=True)
        try:
            pages = await ingest_one(paths, provider, sp, text, tid)
            elapsed = time.time() - t0
            print(f"    -> {len(pages)} page(s) in {elapsed:.0f}s", flush=True)
            for p in pages:
                print(f"       - {p.id} ({p.schema_type if hasattr(p, 'schema_type') else '?'})", flush=True)
            results.append({"file": fname, "status": "ok", "pages": len(pages)})
        except Exception as e:
            elapsed = time.time() - t0
            err_msg = str(e)[:200]
            print(f"    FAILED in {elapsed:.0f}s: {type(e).__name__}: {err_msg}", flush=True)
            results.append({"file": fname, "status": "error", "error": err_msg})

        # Inter-file delay to avoid rate limiting
        if idx < total:
            print(f"    (waiting {INTER_FILE_DELAY}s before next file...)", flush=True)
            await asyncio.sleep(INTER_FILE_DELAY)

    # --- Summary ---
    print(flush=True)
    print("=" * 50, flush=True)
    print("SUMMARY", flush=True)
    print("=" * 50, flush=True)
    ok = sum(1 for r in results if r["status"] == "ok")
    err = sum(1 for r in results if r["status"] == "error")
    print(f"Success: {ok} | Failed: {err} | Total: {len(results)}", flush=True)
    for r in results:
        status_icon = "OK" if r["status"] == "ok" else "FAIL"
        detail = f"{r['pages']} pages" if r["status"] == "ok" else r["error"][:80]
        print(f"  [{status_icon}] {r['file']}: {detail}", flush=True)
    print(flush=True)

    # Check wiki output
    wiki_subdirs = ["sources", "concepts", "entities", "synthesis"]
    print("Wiki output:", flush=True)
    for sd in wiki_subdirs:
        d = paths.wiki / sd
        if d.exists():
            count = len(list(d.glob("*.md")))
            print(f"  wiki/{sd}/: {count} file(s)", flush=True)
        else:
            print(f"  wiki/{sd}/: (not created yet)", flush=True)

    return 1 if err else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
