# Task 4 — Compiler quality and publish gates

Implement the shared compiler gate for LLM completion and status semantics.

Write set: `src/kc/views/book/wiki/compiler.py`, focused compiler/quality tests only.

Requirements:
- Formal apply must not publish rule-only or partial/failed LLM output.
- Successful complete LLM generation must report `llm_status=passed`; no call is `disabled`; unavailable provider is `unavailable`; failed chapter generation is `failed`.
- Preserve old CURRENT pointer on every failed path.
- Do not implement CLI parsing or edit rules loader/polish prompt files.
- Work with existing dirty Book code; make the smallest compatible change.
- Follow TDD and report exact tests.
