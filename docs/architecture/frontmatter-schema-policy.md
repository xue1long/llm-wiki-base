# Frontmatter Schema Policy (`_ko_extra` evolution)

> Reference: [`docs/superpowers/plans/2026-08-26-kc-spec-roadmap.md`](../superpowers/plans/2026-08-26-kc-spec-roadmap.md) §C-0 "Frontmatter Schema 演进".

## 1. Background

`_ko_extra` is the **frontmatter serialization layer's "undeclared-field escape hatch"** for `WikiPage`. It is **not** a structured field — it is a free-form `dict` that lets the Generator, Evidence adapters, and legacy callers stash transient or cross-cutting payloads without forcing a schema change on every commit.

Four classes of business data have historically lived in `_ko_extra`:

| Key                          | Owning subsystem                |
|------------------------------|---------------------------------|
| `_ko_extra.evidence`         | Evidence persistence (C-0 #4)   |
| `_ko_extra.provenance`       | Evidence internal (spec §5.7)   |
| `_ko_extra.source_status`    | Workflow state (C-0 #1)         |
| `_ko_extra.memory.decision`  | Decision records (C-0 #2)       |

The route v2.2 plan **does not delete `_ko_extra`** — it migrates three of those four keys to first-class `WikiPage` fields while preserving the fourth (`provenance`) as a `_ko_extra` internal key.

## 2. Final disposition of `_ko_extra` keys (C-0, 4 commits)

| Commit | Source key                    | Disposition                            | Home after C-0           |
|-------:|-------------------------------|----------------------------------------|---------------------------|
|      1 | `_ko_extra.source_status`     | **Migrated** → `WikiPage.workflow_state` (extended value) | top-level field |
|      2 | `_ko_extra.memory.decision`   | **Migrated** → `WikiPage.decision_record: dict \| None`   | top-level field |
|      3 | `_ko_extra.provenance`        | **Preserved** — stays inside `_ko_extra`                  | `_ko_extra.provenance`   |
|      4 | `_ko_extra.evidence`          | **Migrated** → `WikiPage.evidence_refs: list[str]`        | top-level field |

**After C-0 completes**, the only remaining writer to `_ko_extra` is the Generator's `_ko_extra.provenance` payload. The key is preserved deliberately (see §3).

## 3. Why `_ko_extra.provenance` is **preserved, not migrated**

`WikiPage` is the canonical artifact type and its frontmatter schema is the public contract for downstream tooling. Every new top-level field is a permanent commitment: it is read by the indexer, the lint engine, the search service, the schema migrator, and the user-facing CLI. Adding a field is cheap; removing one is a migration.

`provenance` is an **Evidence-internal field** (spec §5.7). Its consumers are the Evidence persistence layer (`src/kc/adapters/wiki_writer.py`) and downstream Evidence retrieval — not the Wiki indexer or the search layer.

Migrating it to a top-level `WikiPage.provenance` field would:

1. **Inflate `WikiPage`** with a payload that has no indexer/search/lint consumer.
2. **Couple** Evidence-internal data to the public WikiPage schema, making
   future Evidence-schema evolution (C-1's `computation_provenance` /
   `structured_provenance` extensions) a WikiPage migration.
3. **Break the read contract** for the existing Evidence adapters that look
   up `page._ko_extra["provenance"]`.

For these reasons, the v2.2 plan deliberately **does not migrate** provenance. It stays inside `_ko_extra` and is preserved as-is through every round-trip.

### Current call sites

- **Write**: `src/pipeline/generator.py:1155, 1384`
  ```python
  page._ko_extra = {"provenance": _provenance_payload}
  ```
- **Read**: `src/kc/adapters/wiki_writer.py:29-35` (and any future Evidence
  adapter that re-attaches provenance to a downstream projection).

### Round-trip contract (test-anchored)

`WikiPage.to_frontmatter_dict()` and `WikiPage.from_dict()` MUST round-trip
the `_ko_extra.provenance` payload byte-for-byte. The contract is pinned by
[`tests/test_wiki/test_ko_extra_provenance_preserved.py`](../../tests/test_wiki/test_ko_extra_provenance_preserved.py) (C-0 #3 regression suite).

## 4. Implementation guidance

When you encounter `_ko_extra.provenance`:

- **Do not migrate it** to a top-level field unless the trigger in §5 fires.
- **Do not strip it** on read — preserve the entire `_ko_extra` dict so
  other (legacy) sub-keys continue to round-trip until their own commit
  migrates them.
- **Do not add new write sites** for `_ko_extra` other than provenance.
  After C-0 #4 completes, the only remaining writer must be the
  Generator's provenance payload.

## 5. Future deprecation trigger

The "preserve provenance in `_ko_extra`" decision is **revisable, not final**.
Promote provenance to a top-level `WikiPage.provenance` field when **any** of the following becomes true:

1. **Index/search/lint consumer appears.** A non-Evidence subsystem needs
   to enumerate provenance across pages (e.g. a "show me all pages that
   quote source X" report).
2. **Schema-level evolution pressure.** The Evidence `provenance` payload
   grows new structured fields that need their own migration story — at
   that point the simpler choice may be a dedicated top-level field with
   its own migrator.
3. **Cross-cutting access pattern.** A second business domain (e.g.
   citation, bibliography export) starts reading provenance; the
   "Escape hatch in `_ko_extra`" rationale no longer applies.

Until any of those triggers fires, provenance remains a `_ko_extra` key.
The first commit to propose migration must (a) cite which trigger fires,
(b) update this document, and (c) land a separate route plan amendment.