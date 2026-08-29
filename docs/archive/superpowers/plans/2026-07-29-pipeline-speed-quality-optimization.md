# Pipeline Speed & Quality Optimization

**Date:** 2026-07-29
**Context:** Random ingest of 5 raw docs revealed MiniMax-M3 JSON parse
failure rate of 50%, causing 3-7x latency penalty via two-step fallback.
Ollama (qwen3.5-9b) is available locally but unused.

## Root Cause Map

```
MiniMax-M3 unreliable JSON (50% failure)
  ├─ unified path fails → falls back to two-step (Analyzer + Generator)
  │   └─ each step: 1-2 LLM calls → 2-4 calls per task instead of 1
  │       └─ 68s (unified) → 470-490s (fallback) = 7x slowdown
  ├─ Concurrency capped at 2 (fear of MiniMax rate limits)
  │   └─ Ollama local has NO rate limits → unnecessary bottleneck
  └─ Excessive stub creation (17 stubs for 1018-char file)
      └─ LLM generates many [[wikilinks]] → all missing slugs → stubs
```

## Phase 1: Quick Wins (30 min, no code changes)

### 1.1 Switch to Ollama

Ollama is already running (v0.32.5), provider configured, and `qwen3.5-9b-gemini` model loaded. Just switch:

```powershell
# Set env var (takes precedence over MiniMax which is set_default)
$env:RUFLO_LLM_PROVIDER = "ollama"

# Or via CLI (writes to ~/.config/ruflo-kb/llm-providers.json):
python -m src.cli llm-providers set-default ollama

# Restart server
python -m src.cli serve --host 127.0.0.1
```

**Expected:** JSON parse failures drop to near-zero. Ollama respects `response_format` with JSON schema.
**Risk:** qwen3.5 quality may differ from MiniMax-M3 for CJK content extraction.

### 1.2 Increase Concurrency to 4

Ollama on localhost has no rate limits (unlike MiniMax). Bump from 2 to 4:

```python
# src/pipeline/service.py:36
DEFAULT_MAX_CONCURRENCY = 2  # → 4
```

**Expected:** 2x throughput for batch ingestion (4 concurrent LLM calls instead of 2).
**Risk:** Ollama on CPU may throttle at >4 concurrent. Test with 4 first.

## Phase 2: JSON Parsing Hardening (1 hour)

### 2.1 Enhanced Markdown Fence Extraction

`src/pipeline/_pipeline_common.py:77-167` (`parse_llm_json`) already has 4 fallback strategies but still fails on MiniMax output. Diagnostic: MiniMax-M3 returns 13K-46K chars of *prose with embedded JSON*, not just JSON in a fence.

**Fix:** Add strategy 0 (before strict `json.loads`): attempt to locate `{` or `[` near the END of the response (last 25%), since MiniMax often puts JSON after explanatory text.

```python
# In parse_llm_json(), after trimming but before json.loads:
# Strategy 0: try JSON from the last balanced object/array
# (MiniMax often appends JSON after long explanations)
if not content.startswith(("{", "[")):
    last_brace = max(content.rfind("{"), content.rfind("["))
    if last_brace > len(content) * 0.75:  # JSON in last 25%
        content = content[last_brace:]
```

**Expected:** Additional 20-30% of MiniMax responses become parseable.
**Risk:** Low — this is additive, existing fallbacks remain.

### 2.2 Log Unparseable Responses for Debugging

When all strategies fail, save the LLM response to `.index/staging/failed_json/` so patterns can be analyzed.

```python
# In parse_llm_json(), before raising:
import tempfile, os
debug_dir = os.environ.get("RUFLO_JSON_DEBUG_DIR", ".index/staging/failed_json")
os.makedirs(debug_dir, exist_ok=True)
with open(os.path.join(debug_dir, f"failed_{hashlib.md5(content.encode()).hexdigest()[:12]}.txt"), "w") as f:
    f.write(content)
```

**Expected:** Discoverable patterns for future fixes.
**Risk:** Disk usage — rotate with max 100 files.

## Phase 3: Stub Quality Gate (45 min)

### 3.1 Maximum Stubs Per Ingest

`src/pipeline/ingest.py:609`: Add a threshold — if stub count exceeds a configurable max, skip stub creation and log a warning.

```python
MAX_STUBS_PER_INGEST = 10  # or env var

if len(missing) > MAX_STUBS_PER_INGEST:
    _logger.warning(
        "[run_ingest] suppressing %d stubs (exceeds max %d): %s",
        len(missing), MAX_STUBS_PER_INGEST,
        ", ".join(list(missing)[:20]),
    )
    missing = set()
```

**Expected:** Cleaner wiki with fewer C-grade placeholder noise pages.
**Risk:** Legitimate new concepts from rich documents may not get stubs. Mitigate by setting threshold high enough (10).

### 3.2 Exclude Non-Domain Slugs from Stub Creation

The 17 stubs from the 巫术 ingest included "飞书云文档", "北京圣东方国信科技有限公司" — these are platform/organization entities, not writing concepts. Add a blocklist:

```python
STUB_BLOCKLIST = {
    "feishu-yunwendang", "beijing-shengdongfang-guoxin-keji-youxiangongsi",
    "feishu", "yunque",  # platform names
}
# In the stub loop:
if slug_id in STUB_BLOCKLIST:
    continue
```

**Expected:** Fewer noise stubs.
**Risk:** Blocklist needs maintenance. Future: make it configurable per-project.

## Phase 4: Per-Project Provider (2 hours, medium complexity)

### 4.1 Add `llm_provider` Field to `ProjectIdentity`

```python
# src/project/identity.py
@dataclass
class ProjectIdentity:
    id: str
    name: str
    created_at: int
    schema_version: str = "v2.0"
    llm_provider: str | None = None  # ← NEW
    llm_model: str | None = None     # ← NEW
```

### 4.2 Thread Provider Through Pipeline

Update `_get_provider()` to accept an optional `project_id`:

```python
# src/pipeline/__init__.py
def _get_provider(project_id: str | None = None):
    if project_id:
        from ..project.context import ProjectContext
        ctx = ProjectContext.load(project_id)
        if ctx.identity.llm_provider:
            return create_llm_provider(ctx.identity.llm_provider)
    # Fallback to global
    ...
```

### 4.3 CLI Support

```bash
python -m src.cli project set-provider <project_id> ollama
python -m src.cli project set-model <project_id> qwen3.5-9b-gemini:latest
```

**Expected:** Different projects can use different providers (cheap local for bulk ingest, premium cloud for quality-critical tasks).
**Risk:** Increases complexity. Keep global default as fallback.

## Implementation Priority

| Priority | Phase | Effort | Impact | Risk |
|----------|-------|--------|--------|------|
| 🔴 P0 | 1.1 Switch to Ollama | 5 min | **10x** (JSON reliability) | Low |
| 🔴 P0 | 1.2 Concurrency → 4 | 1 min | **2x** throughput | Low |
| 🟡 P1 | 2.1 Enhanced JSON parsing | 30 min | **30%** fewer failures | Low |
| 🟡 P1 | 2.2 Debug logging | 15 min | **Discoverability** | None |
| 🟢 P2 | 3.1 Stub threshold | 20 min | **Cleaner wiki** | Low |
| 🟢 P2 | 3.2 Domain blocklist | 15 min | **Less noise** | Low |
| 🔵 P3 | 4.1-4.3 Per-project provider | 2h | **Flexibility** | Medium |

## Success Metrics

| Metric | Before | After (P0 only) | After (P0+P1) |
|--------|--------|-----------------|---------------|
| JSON parse failure rate | 50% | <5% | <2% |
| Avg ingest time (small doc) | 491s | <60s | <50s |
| Stub % of total pages | 50%+ | 50%+ | <30% |
| Concurrent LLM calls | 2 | 4 | 4 |

## Files to Modify

| File | Change |
|------|--------|
| `src/pipeline/service.py:36` | `DEFAULT_MAX_CONCURRENCY` 2→4 |
| `src/pipeline/_pipeline_common.py:77` | Add "last JSON block" extraction |
| `src/pipeline/_pipeline_common.py:164` | Add debug log dump |
| `src/pipeline/ingest.py:609` | Add `MAX_STUBS_PER_INGEST` threshold |
| `src/pipeline/ingest.py:530+` | Add `STUB_BLOCKLIST` |
| `src/project/identity.py:15` | Add `llm_provider`/`llm_model` fields |
| `src/pipeline/__init__.py:21` | Thread `project_id` through `_get_provider` |
