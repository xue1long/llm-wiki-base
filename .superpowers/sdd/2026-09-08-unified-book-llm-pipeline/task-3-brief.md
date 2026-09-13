# Task 3 — LLM prompt trust boundary

Implement only prompt construction changes for chapter polishing.

Write set: `src/kc/views/book/wiki/polish_llm.py`, focused polish tests.

Requirements:
- Keep current structured output contract and provenance validation.
- Add an explicit fixed hard-contract layer and a clearly delimited project-rules layer before chapter source data.
- If the provider message API supports system messages, put the non-overridable contract there; otherwise keep deterministic post-generation validation authoritative.
- Do not edit compiler, preflight, CLI, or rules loader.
- No tools, filesystem operations, or provider capabilities may be added.
- Follow TDD and report exact tests.
