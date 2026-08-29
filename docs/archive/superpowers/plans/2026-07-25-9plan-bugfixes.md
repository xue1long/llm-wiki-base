# 9-Plan Audit Bugfixes (2026-07-25) — Revised

**Goal:** Fix the 5 bugs/gaps surfaced by the 2026-07-25 audit of Plans 1-9, with corrections from a second-pass logic review.

**Scope:**
- P0: Plan 7 `/metrics` HTTP endpoint dead (returns 404)
- P1: Plan 3/4 quality gate not inline in ingest pipeline
- P2: Plan 5 spec drift (API names differ from spec)
- P3: Plan 25 v1 wiki-templates CLI missing
- P4: Plan 9 vision uses text-only LLM instead of native vision API (deferred)

**Revisions in this version (vs first-pass):**
- P0: Clarify `get_router()` DB-path locking (caches at first call)
- P1: Define judge LLM failure fallback (default=pass+log) and retry semantics (re-generate, not re-judge)
- P2: Specify `_default_name` slot in 4-tier resolution (env > explicit > "default" alias > first persisted > first overall); extend `save()`; **drop `add` alias** (keep `list` + `set_default` only)
- P3: Use `--project <name>` (project name, per spec) not path; add `--yes` to `reset`; warn if `edit` removes template headers
- Add: Pre-commit hook wraps YAML errors as warning, not blocker
- Execution order revised: P0 → P3 → P2 → P1 (P1 wants P0 metrics for quarantine counters)

**Total estimated effort:** ~4-6 hours of focused work (P0+P2+P3), plus 2-3 hours for P1 after user decisions.

---

## Task 1: Mount `/metrics` HTTP endpoint (P0) — REVISED

**Files:**
- Modify: `src/server/app.py`
- Add: `tests/test_server/test_metrics_endpoint.py`

**Root cause:** `src/server/metrics_route.py:18` provides `get_router()` but `src/server/app.py:92-95` only includes 8 routers. `GET /metrics` returns 404.

**Fix:** Add 2 lines to `src/server/app.py` after the existing `app.include_router(router)` loop:

```python
from .metrics_route import get_router
# ... after the existing include_router loop ...
app.include_router(get_router())
```

`get_router()` is idempotent (caches at module level, see `metrics_route.py:13`), so calling multiple times is safe.

**New note (revised):** The DB path is resolved inside `get_router()` on first call via `config_dir()` (per-project) with fallback to `~/.config/ruflo-kb` (user-global). The path is then cached at the module-level `_router` variable. **Implication:** If a server is restarted with a different project, the metrics DB location is determined by the FIRST `get_router()` call (typically the lifespan startup). Multi-project server deployments would need a different design (out of scope; document in app.py docstring).

**Tests:** `tests/test_server/test_metrics_endpoint.py`:
- `test_metrics_endpoint_returns_200` — `client.get("/metrics")` returns 200
- `test_metrics_endpoint_returns_prometheus_format` — body matches `^# HELP|# TYPE|<metric> <value>` pattern
- `test_metrics_endpoint_idempotent` — calling `get_router()` twice returns the same router (same id)
- `test_metrics_endpoint_persists_counter` — write a counter, GET /metrics, verify row in metrics.db

**Acceptance:**
- `curl http://127.0.0.1:19828/metrics` returns 200 with Prometheus text
- `python -m pytest tests/test_server/test_metrics_endpoint.py -v` passes
- Existing 828 tests still pass

**Effort:** 10 minutes.

---

## Task 2: Pre-commit hook safety wrap (NEW, was unmentioned)

**Files:**
- Modify: `scripts/sync_wiki_spec.py`
- Modify: `.git/hooks/pre-commit` (regenerate via setup_git_hooks.py)

**Root cause:** Currently `sync_wiki_spec.py` raises unhandled `yaml.YAMLError` if the spec has invalid YAML. The pre-commit hook calls it via `subprocess.run(..., cwd=...)` with `sys.exit(result.returncode)` — so a YAML error blocks ANY commit (even unrelated ones).

**Fix:** Wrap the spec parse in try/except in `sync_wiki_spec.py`:

```python
def main() -> int:
    if not SPEC_PATH.exists():
        print(f"WARN: {SPEC_PATH} not found, skipping sync", file=sys.stderr)
        return 0  # already correct
    try:
        current_md5 = _compute_md5(SPEC_PATH)
        # ... existing code
    except yaml.YAMLError as e:
        print(f"WARN: spec YAML parse error: {e}; skipping sync", file=sys.stderr)
        return 0  # do not block the commit
    except Exception as e:
        print(f"ERROR: sync failed: {e}", file=sys.stderr)
        return 1  # unknown error: block
```

**Important:** Only YAML errors (and missing file) should NOT block. Other errors (PermissionError, disk full) should still block — they indicate real problems.

**Tests:** `tests/test_scripts/test_sync_wiki_spec.py`:
- `test_sync_skips_on_missing_spec` (already passes)
- `test_sync_warns_on_yaml_error` — write invalid YAML to spec, run sync, expect exit 0 + stderr warning
- `test_sync_still_fails_on_permission_error` — mock open() to raise, expect exit 1
- `test_sync_silent_on_no_change` (NEW) — run twice, second run should exit 0 silently (or with --verbose)

**Effort:** 15 minutes.

---

## Task 3: QualityGate pipeline integration (P1) — REVISED with 3 design decisions

**This task is BLOCKED on 3 user decisions before implementation. List them at the top; do not implement until user signs off.**

### 3.0 User decisions required

**Decision A: Fallback when judge LLM is unavailable**

The judge makes an LLM call. It can fail (network, auth, rate limit, timeout). What should happen?

| Option | Behavior | Pros | Cons |
|---|---|---|---|
| **A1** (recommended) | Default verdict=pass, log warning, page proceeds to wiki | Judge outage doesn't break ingest | Bad pages slip through during outage |
| A2 | Default verdict=reject, quarantine | Conservative during outage | Outage = all pages quarantined = wiki empty |
| A3 | Fail ingest | Strict | Single judge outage = 100% ingest failure |

**Default: A1.** Aligns with Plan 19/20/21 audit's principle: quality gates must not block the main flow.

**Decision B: Retry semantics**

Spec says "1 retry per page". Two interpretations:

| Option | Behavior | Latency cost | Pros | Cons |
|---|---|---|---|---|
| **B1** (recommended) | Retry = re-call Generator, re-judge the new output | 2x (analyze + generate + 2x judge) | Different LLM completion might pass | 2x cost |
| B2 | Retry = re-judge same output with different random seed | +1 judge call | Cheap | Same prompt rarely gives different score; mostly wasted |

**Default: B1.** Plus set `QualitySettings.max_retries: int = 0` (off by default) to avoid the 2x cost. User opts in via config.

**Decision C: Mode (inline vs async) — already in first-pass**

Three options:
- A: inline only
- B: async only
- C: both, behind `QualitySettings.enabled` flag (recommended)

**Default: C with `enabled=False` (off by default).** Spec already has `QualitySettings.enabled` field. Off-by-default avoids breaking existing ingests; user opts in.

### 3.1 Implementation outline (after user decisions)

**Files:**
- Modify: `src/pipeline/ingest.py` (call judge after Generator)
- Modify: `src/quality/judge.py` (add fallback + retry logic)
- Modify: `src/quality/__init__.py` (export new symbols)
- Add: `tests/test_quality/test_pipeline_integration.py`

**Logic in `run_ingest` (post-Generator):**

```python
# After generate() returns pages
from ..quality.judge import QualityJudge
from ..quality.types import QualitySettings, BatchJudgmentResult

settings = QualitySettings.from_project_config(paths)  # or hardcode default
if settings.enabled:
    try:
        judge = QualityJudge(ctx=ctx, settings=settings)
        result = await judge.judge_batch(pages, analysis)
        if result.pages_rejected:
            # Per Decision A1: only reject on actual judgment, not on judge failure
            # Per Decision B1: re-generate rejected pages up to max_retries
            for retry_round in range(settings.max_retries):
                if not result.pages_rejected:
                    break
                # Re-call generate() with hints about why pages were rejected
                result = await judge.judge_batch(
                    await generate(paths, analysis, ...),
                    analysis,
                )
            # Final disposition
            pages_to_write = [p for p in pages if p.id not in result.pages_rejected_final]
            quarantined = [p for p in pages if p.id in result.pages_rejected_final]
            quarantine_store.put(quarantined, result.judgments)
    except Exception as e:
        # Decision A1: judge LLM failure → pass through with warning
        _logger.warning(f"QualityJudge unavailable: {e}; passing pages through")
```

**Tests:**
- `test_judge_inline_runs_after_generator` — mock generator, verify judge called
- `test_judge_failure_does_not_block_ingest` (Decision A1) — judge raises, pages still written
- `test_judge_retry_regenerates` (Decision B1) — first call rejects, retry calls generate again
- `test_judge_disabled_skips` (Decision C) — `enabled=False` → judge not called, no latency
- `test_judge_quarantine_atomic` — verify quarantine_store.put is atomic (already covered in existing quarantine tests)

**Effort:** 2-3 hours including tests.

---

## Task 4: ProviderRegistry aliases to match spec (P2) — REVISED

**Files:**
- Modify: `src/llm/registry.py`
- Modify: `src/llm/registry.py` (save() to persist `_default_name`)
- Add: `tests/test_llm/test_registry_aliases.py`

**Spec drift:** spec said `add/list/get/set-default`; actual is `upsert/load/get/get_default` (read-only).

**Revisions from first-pass:**
- **Drop the `add()` alias** — `add` is a generic name that conflicts with `set.add`, `dict.fromkeys` etc; `upsert` is more specific.
- **Keep `list()` alias for `load()`** — `list` is intuitive for read.
- **Add `set_default(name)` mutator** — new behavior (current `get_default` is read-only).
- **`_default_name` slot in resolution order** — position it AFTER env var, BEFORE existing tiers.

**New 5-tier resolution order** in `get_default()`:

```
1. $RUFLO_LLM_PROVIDER env var (highest)
2. Explicit `_default_name` from registry (NEW)
3. Provider named "default" (back-compat alias)
4. First persisted (non-env-sourced)
5. First provider (fallback)
```

**`save()` extension:**

Current `save(providers: dict[str, ProviderConfig])` only writes `{"providers": {...}}`. New signature: `save(providers: dict, default_name: Optional[str] = None)`. When `default_name` is non-None, write `{"providers": {...}, "default": "<name>"}`. When None, write `{"providers": {...}, "default": null}`.

**Migration handling:** Old `llm-providers.json` files have no `"default"` key. `load()` returns `_default_name=None`; `get_default()` falls through to tier 3 ("default" alias or first persisted). New `set_default("X")` call → save with `"default": "X"`. No data loss.

**Fix:**

```python
@staticmethod
def load() -> dict[str, ProviderConfig]:
    # ... existing code ...
    data = json.loads(text)
    return {
        k: ProviderConfig.from_dict(v)
        for k, v in data.get("providers", {}).items()
    }, data.get("default")  # NEW: return _default_name too

@staticmethod
def save(providers: dict[str, ProviderConfig], default_name: Optional[str] = None) -> None:
    # ... existing write logic, but include "default" field
    payload = {
        "providers": {k: v.to_dict() for k, v in providers.items()},
        "default": default_name,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

@staticmethod
def set_default(name: str) -> None:
    """Set the explicit default provider (Decision Tier 2 in get_default)."""
    if name not in ProviderRegistry.load():
        raise ProviderNotFoundError(name)
    existing = ProviderRegistry.load()
    ProviderRegistry.save(existing, default_name=name)

# Aliases
def list(self) -> dict[str, ProviderConfig]:
    """Alias for load() — matches spec terminology."""
    return self.load()
```

**Tests:**
- `test_list_alias_returns_same_as_load` — `registry.list() == registry.load()`
- `test_set_default_persists_to_disk` — `set_default("ollama")` → reload → `get_default().name == "ollama"`
- `test_set_default_unknown_raises` — `set_default("nonexistent")` → ProviderNotFoundError
- `test_get_default_env_overrides_explicit` — set_default("ollama") + env="openai" → returns openai
- `test_get_default_explicit_overrides_default_alias` — set_default("ollama") + provider named "default" exists → returns ollama
- `test_load_old_file_without_default_field` — pre-existing `{"providers": {...}}` loads with `_default_name=None`, get_default falls through to tier 3/4/5
- `test_save_then_load_roundtrip` — set_default + reload preserves both providers and default

**Acceptance:**
- All 828 existing tests still pass
- `python -m pytest tests/test_llm/test_registry_aliases.py -v` passes
- Existing CLI commands (which use canonical `upsert/load/get/get_default`) still work

**Effort:** 45 minutes (revised from 30; new save() signature + migration test).

---

## Task 5: wiki-templates CLI (P3) — REVISED with safety + spec alignment

**Files:**
- Add: `src/cli_ext/wiki_templates_cmd.py`
- Modify: `src/cli.py` (register subcommand)
- Add: `tests/test_cli_ext/test_wiki_templates_cmd.py`

**Revisions from first-pass:**
- **`--project` takes project NAME (per Plan 25 spec), not path** — resolve via `src.lib.project.resolve_project` or equivalent
- **`reset` requires `--yes` flag** for non-interactive confirmation
- **`reset` prints removed path** + creates `.bak` next to it
- **`edit` validates header preservation** — if user removes the 2 `<!-- wiki-template-* -->` lines, fail loudly with diff
- **`edit --no-open` flag** for CI / no `$EDITOR` environments
- **Header DO-NOT-EDIT comment** at top of copied template

**Subcommands (revised):**

```
python -m src.cli wiki-templates list
  # Show all 4 PageTypes with version + source + validity

python -m src.cli wiki-templates show concept
  # Print template body_markdown to stdout

python -m src.cli wiki-templates edit concept
  # Copy bundled/concept.md to ~/.config/ruflo-kb/wiki-templates/concept.md
  # Add "DO NOT EDIT THE 2 HEADER LINES BELOW" comment
  # Open in $EDITOR (click.edit); fallback to notepad on Windows

python -m src.cli wiki-templates edit concept --project novel-wiki
  # Copy to <project>/.wiki-templates/concept.md
  # (--project takes project NAME, resolved via registry)

python -m src.cli wiki-templates edit concept --no-open
  # Copy without opening editor (CI / scripted use)

python -m src.cli wiki-templates reset concept --yes
  # Remove ~/.config/ruflo-kb/wiki-templates/concept.md
  # Back up to concept.md.bak in the same dir
  # Print "Removed: <path>, backup at: <path>.bak"
  # --yes required for non-interactive use (default: prompt or error in CI)
```

**Tests:**
- `test_list_shows_all_four_types`
- `test_list_marks_invalid_templates` — file with missing/malformed `<!-- wiki-template-type -->` → marked ⚠️ INVALID
- `test_show_concept_prints_template_body`
- `test_edit_copies_bundled_to_user_dir`
- `test_edit_adds_do_not_edit_header_comment`
- `test_edit_project_resolves_project_name_to_path`
- `test_edit_no_open_skips_editor`
- `test_reset_requires_yes_flag_in_ci`
- `test_reset_creates_bak_file`
- `test_reset_prints_removed_path`
- `test_show_unknown_type_errors_gracefully`

**Effort:** 2 hours (revised from 1-2; added 5 safety tests).

---

## Task 6: Plan 9 native vision API (P4) — DEFERRED, no change

**Status:** Out of MVP scope per `src/vision/captioner.py:54-57`. The text-only LLM fallback is acceptable for the MVP that the plan targeted.

**No action this session.** Track as v2.0.1.

---

## Recommended execution order (REVISED)

| # | Task | Why this order | Effort |
|---|---|---|---|
| 1 | **P0 metrics** (Task 1) | Foundation; needed by P1 for quarantine counter | 10 min |
| 2 | **Pre-commit hook wrap** (Task 2) | Prevents accidental commit blocks; unrelated to other tasks | 15 min |
| 3 | **P3 templates CLI** (Task 5) | Self-contained; fills gap I created in Plan 25 | 2 hours |
| 4 | **P2 registry aliases** (Task 4) | Self-contained; spec drift fix; needed before P1 (P1 reads `get_default`) | 45 min |
| 5 | **P1 QualityGate pipeline** (Task 3) | After user decisions + after P0/P3/P2 land | 2-3 hours |
| 6 | **P4 vision** (Task 6) | Defer | — |

**Total for Task 1+2+3+4:** ~3.5 hours
**Total with P1 (Task 3):** ~6 hours

---

## User decisions required before execution

1. **Task 3 (P1) Decision A: Judge LLM failure fallback** — A1 (default=pass+log) / A2 (default=reject+quarantine) / A3 (fail ingest)? **Default: A1.**
2. **Task 3 (P1) Decision B: Retry semantics** — B1 (re-generate, default `max_retries=0`) / B2 (re-judge)? **Default: B1.**
3. **Task 3 (P1) Decision C: Mode** — A (inline) / B (async) / C (both, `enabled=False` default)? **Default: C.**

**Reply with your choices (or "use defaults") and I will execute Tasks 1, 2, 4, 5 immediately without further questions.** Task 3 will follow after your decision.

---

## What I will NOT do (unchanged from first-pass)

- Plan 25 v2 (conditional slots) and v3 (versioning + migration CLI) — needs separate plan
- Plan 9 native vision — explicitly deferred; needs separate plan
- Global registry test pollution cleanup — orthogonal; separate plan
- Quality gate inline implementation — needs your 3 decisions first
