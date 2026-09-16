"""Reconciliation subsystem (Tasks 27-32 of the v7 stage remediation plan).

The reconciliation subsystem decides *which wiki page refers to which
underlying concept* — turning noisy per-source entity mentions into a
small, stable set of canonical concepts.

Module layout (each task adds one):
  * ``canonical_models``    (Task 27) — canonical_id, AliasRecord,
    ReconciliationDecision vocabulary, SlugAliasRegistryAdapter stub.
  * ``candidate_retrieval`` (Task 28) — 6 retrieval strategies.
  * ``llm_resolver``        (Task 29) — LLM-driven decision emit.
  * ``apply_decisions``     (Task 30) — priority-ordered decision application
    + SlugAliasRegistry wiring (F15).
  * ``store``               (Task 31) — durable canonical store + JSON
    persistence.
  * ``promotion``           (Task 32) — hook reconcile() into the v7
    pipeline.

Identity Contract
-----------------
``canonical_id`` and ``decision_id`` are *script-owned* (uuid4 / sha1 of
deterministic inputs). The LLM never produces these ids (Task 29 will
assert this at the prompt boundary).

Failure Contract
----------------
Helper functions (``new_canonical_id``, ``decision_id_for``,
``SlugAliasRegistryAdapter.register_alias``) never raise. They are
called from the hot path of the pipeline; turning exceptions there
would block every page that needs reconciliation.
"""