# 9-Plan Audit Bugfixes (2026-07-25)

**Goal:** Fix the 5 bugs/gaps surfaced by the audit of Plans 1-9 (2026-07-25).

**Scope:**
- P0: Plan 7 `/metrics` HTTP endpoint dead (returns 404)
- P1: Plan 3/4 quality gate not inline in ingest pipeline
- P2: Plan 5 spec drift (API names differ from spec)
- P3: Plan 25 v1 wiki-templates CLI missing
- P4: Plan 9 vision uses text-only LLM instead of native vision API (deferred)

**Total estimated effort:** ~4-6 hours of focused work (P0+P2+P3), plus design discussion for P1.

---

## Task 1: Mount `/metrics` HTTP endpoint (P0)

**Files:**
- Modify: `src/server/app.py`
- Add: `tests/test_server/test_metrics_endpoint.py`

**Root cause:** `src/server/metrics_route.py:18` provides `get_router()` but `src/server/app.py:92-95` only includes 8 routers. The metrics router is dead code — `GET /metrics` returns 404.

**Fix:** Add 2 lines to `src/server/app.py` after the existing `app.include_router(router)` loop:

```python
from .metrics_route import get_router
# ... after the existing include_router loop ...
app.include_router(get_router())
```

`get_router()` is idempotent (caches at module level, see `metrics_route.py:13`), so calling it multiple times is safe.

**Tests:** Add `tests/test_server/test_metrics_endpoint.py`:
- `test_metrics_endpoint_returns_200` — `client.get("/metrics")` returns 200
- `test_metrics_endpoint_returns_prometheus_format` — body matches `^# HELP|# TYPE|<metric> <value>` pattern
- `test_metrics_endpoint_idempotent` — calling `get_router()` twice returns the same router

**Acceptance:**
- `curl http://127.0.0.1:8765/metrics` returns 200 with Prometheus text
- `python -m pytest tests/test_server/test_metrics_endpoint.py -v` passes
- Existing 828 tests still pass

**Effort:** 5 minutes.

---

## Task 2: Decide on Plan 3/4 quality gate pipeline integration (P1 — design decision)

**Question for user:** Should the QualityJudge run inline in `run_ingest`, or stay CLI-only?

**Options:**

**Option A: Inline (matches plan spec)**
- `run_ingest` calls `QualityJudge.judge_batch(pages, source_text)` after Generator
- Pages with verdict="reject" go to quarantine, not to wiki write
- Quarantined pages get re-tried once (`max_retries=1`); second failure → final quarantine
- Latency: +5-15s per ingest (LLM judge call)
- Pros: matches spec, immediate feedback
- Cons: every ingest pays the latency cost; judge failures could break ingest

**Option B: Async via event bus**
- `run_ingest` writes pages, emits `GeneratorDone` event
- `QualityJudge` listens to `GeneratorDone`, runs asynchronously, writes verdicts
- Quarantine is a flag on the page; reader UI can show "this page was quarantined"
- Latency: zero added to ingest
- Pros: non-blocking
- Cons: pages briefly exist before being quarantined (could be cached/linked before quality check)

**Option C: Both, behind a feature flag**
- `QualitySettings.enabled` (already in the plan spec) — default true → inline, false → CLI-only
- Pros: flexibility, users can opt out
- Cons: more code to maintain

**Recommended:** Option C (inline by default, can disable). It matches the spec's `QualitySettings.enabled` field and gives escape hatch for users who don't want the latency cost.

**Effort:** 2-3 hours including tests.

**Defer this decision to user** — do not implement without explicit answer.

---

## Task 3: Add Plan 5 API aliases to match spec (P2)

**Files:**
- Modify: `src/llm/registry.py`
- Add: `tests/test_llm/test_registry_aliases.py`

**Spec drift:**
- Spec said: `add/list/get/set-default`
- Actual: `upsert/load/get/get_default` (where `get_default` is read-only)
- Functionality is complete (CLI calls `upsert` for add, `load` returns dict for list) but API names diverge

**Fix:** Add 4 thin aliases to `ProviderRegistry`:

```python
# Aliases for spec compatibility (add/list/get/set-default)
def add(self, config): return self.upsert(config)
def list(self): return self.load()
def set_default(self, name): self._default_name = name; self.save()  # mutator
```

The existing `upsert/load/get/get_default` stay as the canonical names. The aliases are deprecated entry points that just call through.

**Note:** The `set_default` mutator is genuinely new (was previously only `get_default` read). Implementing it requires:
- Adding `_default_name` field to `RegistryState` dataclass
- Persisting `_default_name` in `~/.config/ruflo-kb/llm-providers.json`
- Defaulting `_default_name=None` so existing `get_default()` behavior (returns first entry) still works

**Tests:**
- `test_add_alias_calls_upsert` — `registry.add(config)` and `registry.upsert(config)` produce identical state
- `test_list_alias_returns_dict` — `registry.list()` returns same shape as `registry.load()`
- `test_set_default_persists` — `set_default("ollama")` + reload from disk → `get_default() == "ollama"`
- `test_set_default_does_not_break_existing_get_default` — pre-existing files without `_default_name` still resolve default via first-entry fallback

**Acceptance:**
- `python -m pytest tests/test_llm/test_registry_aliases.py -v` passes
- Existing 828 tests still pass
- Existing CLI commands still work (they use canonical names, aliases are additive)

**Effort:** 30 minutes.

---

## Task 4: Add `wiki-templates` CLI to Plan 25 v1 (P3)

**Files:**
- Add: `src/cli_ext/wiki_templates_cmd.py`
- Modify: `src/cli.py` (register subcommand)
- Add: `tests/test_cli_ext/test_wiki_templates_cmd.py`

**Subcommands to implement** (per Plan 25 spec):
- `wiki-templates list` — show all PageTypes with version + source (bundled/user/project)
- `wiki-templates show <type>` — print template body_markdown
- `wiki-templates edit <type>` — copy bundled to user dir + open $EDITOR
- `wiki-templates edit <type> --project <root>` — copy bundled to project's `.wiki-templates/` + open $EDITOR
- `wiki-templates reset <type>` — remove user/project override (fall back to bundled)

**Implementation notes:**
- Reuse `src.wiki.templates.resolve()` and `list_available()` for read
- For `edit`: copy file with frontmatter headers preserved; the `<!-- wiki-template-type: TYPE -->` and `<!-- wiki-template-version: X.Y.Z -->` lines must NOT be edited (validation will reject on next resolve)
- For `reset`: use `os.unlink` on the override file
- Use `click.edit()` for `$EDITOR` integration (already a click dep) — falls back to `notepad` on Windows

**Tests:**
- `test_list_shows_all_four_types`
- `test_show_concept_prints_template_body`
- `test_edit_copies_bundled_to_user_dir`
- `test_edit_project_copies_bundled_to_project_dir`
- `test_reset_removes_user_override`
- `test_show_unknown_type_errors_gracefully`

**Effort:** 1-2 hours.

---

## Task 5: Plan 9 native vision API (P4 — DEFERRED)

**Status:** Out of MVP scope per `src/vision/captioner.py:54-57`. The text-only LLM fallback is acceptable for the MVP that the plan targeted.

**Why defer:** Implementing native vision API requires:
- Adding `vision_complete(messages, images=[...])` method to `LLMProvider` base class
- Implementing for OpenAI (`gpt-4o` accepts image_url content blocks)
- Implementing for Anthropic (`claude-3-opus` accepts image content blocks)
- Implementing for Ollama (llava/bakllava models accept image inputs)
- New tests with actual images

**Recommended:** Track as v2.0.1 enhancement. The MVP `python -m src.cli vision extract <pdf>` already works for the documented use case (PDF → text captions via LLM).

**No action this session.**

---

## Recommended execution order

1. **Task 1 (P0 metrics)** — 5 min, immediate value
2. **Task 3 (P2 alias)** — 30 min, low risk
3. **Task 4 (P3 templates CLI)** — 1-2 hours, fills the gap I created in Plan 25
4. **Task 2 (P1 design decision)** — ask user, then implement if approved (2-3 hours)
5. **Task 5 (P4 vision)** — defer to v2.0.1

**Total for P0+P2+P3:** ~2-3 hours of focused work.

**Total for P0+P2+P3+P1:** ~4-6 hours.

---

## What I will NOT do

- Plan 25 v2 (conditional slots) and v3 (versioning + migration CLI) — explicitly deferred in my Plan 25 v1 commit message; needs separate plan
- Plan 9 native vision — explicitly deferred in `captioner.py:54-57`; needs separate plan
- Quality gate inline implementation — needs user design decision first
- Global registry test pollution cleanup — orthogonal issue, separate plan
- Sync script silent-on-no-change UX — minor, can fix in this session if user wants
