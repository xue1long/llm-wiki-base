# Task 1 Review Report

## Verdict

- Spec compliance: **FAIL**
- Task quality: **FAIL**

## Critical

- **C1 — API can expose arbitrary manifest data.** `book_wiki_series_manifest()` returns the parsed `series-manifest.json` unchanged (`src/services/files.py:317-323`), and the legacy path embeds the entire old manifest under `manifest` (`src/kc/views/book/wiki/series_validate.py:118-125`). A manifest can therefore add secret-like fields or absolute paths and have them returned by the new API, violating the explicit API boundary. Return a curated public shape and strip unknown fields/paths.

## Important

- **I1 — Active release integrity is bypassed for the new endpoint.** `_active_book_wiki()` calls `resolve_active_version()` directly when `version` is omitted (`src/services/files.py:213-230`), so it does not run `_verified_book_release()`'s `files` hash and path checks. The series endpoint only hashes `series-manifest.json` (`src/services/files.py:309-315`); tampered outline, sidecar, or body files are not validated on this path. The required release-file validation exists as an isolated helper but is not wired into the active series read.

- **I2 — Canonical manifest digest is optional.** `validate_series_manifest()` only checks `manifest_sha256` when the field is present (`src/kc/views/book/wiki/series_validate.py:86-88`). A `series-manifest-v1` payload without a digest is accepted and served, despite the contract requiring the manifest itself to use a canonical digest. The new contract should require a correctly formatted, matching digest.

- **I3 — Legacy fallback manufactures an incorrect ready book state.** The compatibility response always inserts a book with `status: "ready"` (`src/services/files.py:324-328`), even when the old release manifest reports `partial`, `invalid`, or another state. Also, `read_legacy_manifest()` decides legacy status solely from `schema_version` (`src/kc/views/book/wiki/series_validate.py:122-124`), so a malformed payload with `schema_version == series-manifest-v1` but no `series_id` is not treated as anonymous legacy data. This can misrepresent old release state and mishandle the stated missing-`series_id` compatibility case.

## Minor

- `validate_release_files()` rejects every nested path via `path.name != str(name)` (`src/kc/views/book/wiki/series_validate.py:104-107`). That is safe and conservative, but the contract says release-root relative paths; if nested `chapters/...` files are expected, this implementation rejects valid releases. The behavior should be explicit in the contract or covered by a test.

- `SeriesManifest` and `BookManifest` are frozen only at the dataclass level; their list/dict fields remain mutable. This is not a direct contract failure, but callers can mutate a supposedly immutable model after construction.

## Test coverage and verification

The added test file exercises basic model/validator cases, but it does not exercise the new service or route, API field filtering, active-release file verification, digest-required behavior, legacy status preservation, or missing `series_id` handling. The dependency test also does not assert a ready series is rejected when its hard dependency target is from another release. The implementation report says pytest could not run because the available Python launcher was unavailable/denied; only `py_compile` passed. Therefore there is no executable evidence for the required RED/GREEN or server/files regression suite.

