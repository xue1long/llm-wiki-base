# Task 1 Scoped Re-review Report

## Verdict

- Spec compliance: **FAIL**
- Task quality: **FAIL**

## Previous findings

- **C1 API data exposure: PARTIALLY ADDRESSED, still FAIL.** The current series path now returns a curated top-level/book shape and `read_legacy_manifest()` no longer returns the raw manifest. However, `book_wiki_series_manifest()` validates `outline_id` with the non-null `public_id()` guard (`src/services/files.py:338-341`). `validate_book_manifest()` permits `outline_id: null` (and `BookManifest` models it as optional), so a contract-valid series manifest is rejected with `BookWikiUnavailableError`. The legacy path also copies `manifest.get("run_id")` into `release_id` without the same safe-ID validation (`src/services/files.py:345-350`); an old manifest can therefore expose an absolute/path-like or secret-like run id through the API. The public shape has no service/route test.

- **I1 active release integrity bypass: ADDRESSED in wiring.** `_active_book_wiki()` resolves the active pointer and then always calls `_verified_book_release()`, so the series endpoint now checks every file listed by the release manifest before reading `series-manifest.json`. The series manifest must also be listed and match its SHA-256. The implementation still trusts the release `files` mapping as the completeness set; no test proves tampering with an outline/sidecar/body is rejected specifically through the series endpoint.

- **I2 digest optional: ADDRESSED.** `validate_series_manifest()` now requires a lowercase 64-character `manifest_sha256` equal to `canonical_digest(payload)` (`src/kc/views/book/wiki/series_validate.py:86-90`), and the contract test covers omission.

- **I3 legacy status / missing series id: ADDRESSED.** `read_legacy_manifest()` treats missing `series_id` as anonymous legacy even with the current schema, preserves recognized status, and maps unknown status to `invalid`; the fallback book uses that status and does not invent book/outline ids. The added unit coverage checks partial status and missing `series_id`, but does not exercise the service endpoint.

- **Release path strategy: ADDRESSED.** Both release verification paths reject absolute, `..`, and nested paths (`path.name != str(name)`); the added test makes the single-segment release-root policy explicit. This is conservative and consistent with the report's stated strategy.

## Test coverage and verification

Executed with the bundled runtime and a workspace basetemp:

```text
tests/test_kc/test_book_series_manifest.py                         5 passed
tests/test_server/test_service_files.py                            \
tests/test_server/test_kc_book_routes.py                           37 passed
tests/test_kc/test_book_wiki_compiler.py
```

The required contract and related regression tests pass. They do not cover the new `book_wiki_series_manifest()` service or `/book-wiki/series` route, curated-field filtering, unsafe public IDs, active-release tampering through that endpoint, or legacy status at the service boundary. A direct runtime probe also reproduced the nullable-outline regression described under C1.

## Conclusion

The core validator fixes close C1's raw-manifest leak, I1's active-release bypass, I2's optional digest, and I3's status/ownership handling in their primary paths. The implementation is not ready to pass review because the API boundary still rejects a model-valid nullable outline and can return an unsanitized legacy `run_id`, while the required API/integrity behavior lacks executable coverage.
