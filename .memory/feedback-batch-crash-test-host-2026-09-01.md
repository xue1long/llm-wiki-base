## 2026-09-01 batch crash test host workaround

- Symptom: pytest output stopped after a batch executor crash-inject test when a descendant exited with code 137.
- Root cause: the desktop execution host monitors descendant process termination and truncates pytest output; the batch crash hook itself correctly persisted recoverable state.
- Verification: generate, cascade, gate, and commit crash/resume scenarios each reached `PASSED` when run individually.
- Workaround: tests opt into `RUFLO_SOFT_CRASH=1`; the hook still terminates immediately, but exits 0 so the host can finish. The test helper maps that controlled exit back to the expected 137 assertion. Default `BATCH_EXECUTOR_CRASH_AT` behavior remains `os._exit(137)`.
