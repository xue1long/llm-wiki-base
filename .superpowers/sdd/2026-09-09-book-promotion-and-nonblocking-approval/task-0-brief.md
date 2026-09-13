# Task 0 brief — Freeze the candidate-release publication protocol

Read this brief first. It is the exact task requirement.

Implement the first vertical slice of the Book Preview → Apply-from safety protocol in the current workspace. Do not dispatch subagents. Preserve unrelated dirty files and do not call any real provider.

Files in scope:

- `src/kc/views/book/wiki/compiler.py`
- `src/kc/views/book/wiki/acceptance.py` only when a shared validation type/helper is genuinely needed
- `tests/test_kc/test_book_release_protocol.py`

Required behavior:

1. Introduce a typed internal candidate value (named `ValidatedCandidate` or an equally clear local type) so publication code receives validated inputs rather than an arbitrary path.
2. Define candidate identity from canonical manifest bytes. The validator must verify the manifest digest, every manifest-listed file hash, safe relative paths, complete release status, and project/book identity when those fields exist.
3. Bind the candidate to the source snapshot/revision and expose an explicit lifecycle state. Supported lifecycle states are `candidate`, `validated`, `published`, `superseded`, `expired`, and `rejected`. A rejected or expired candidate must not be considered promotable.
4. Keep mutable lifecycle/audit evidence outside the immutable content manifest. Adding lifecycle or human-review evidence must not change the candidate content identity.
5. Add behavior tests at the public compiler seam or the smallest stable exported seam. Tests must cover: valid candidate; changed manifest; changed listed file; missing listed file; unsafe path; wrong project/book identity; rejected/expired lifecycle; and audit/lifecycle sidecar changes not altering content identity.
6. Do not implement CLI parsing, human-approval status changes, budget estimation, or real promotion yet; later tasks consume this protocol.

Verification:

```text
uv run --offline pytest tests/test_kc/test_book_release_protocol.py -q
```

Because the repository currently has a large dirty tree, report only files changed for this task, test results, and any compatibility concern. Do not commit unrelated paths. Write a concise implementation report to `.superpowers/sdd/2026-09-09-book-promotion-and-nonblocking-approval/task-0-report.md`.
