# Task 1 fix round 2 review package

Fix base: a0b1afa8
Fix head: 919d8440

## Findings addressed

- Nullable `outline_id` remains valid at service boundary.
- Legacy `release_id` is anonymous (`null`), so old `run_id` cannot leak.
- Added nullable outline contract regression.

## Required review

Review Task 1 against the brief and the full initial implementation, verify the prior Critical/Important findings are closed, inspect API/service boundary behavior and tests, and run the scoped bundled-Python regression. Treat any remaining integrity, compatibility, security, or coverage gap as a failure.

## Diff
```diff
diff --git a/src/services/files.py b/src/services/files.py
index 2b8c4108..9cdfee49 100644
--- a/src/services/files.py
+++ b/src/services/files.py
@@ -335,8 +335,9 @@ def book_wiki_series_manifest(project_id: str) -> dict:
             public = {key: book[key] for key in (
                 "book_id", "required", "status", "outline_id",
                 "hard_dependencies", "soft_dependencies") if key in book}
-            for key in ("book_id", "outline_id"):
-                public_id(public_id(public.get(key)))
+            public_id(public_id(public.get("book_id")))
+            if public.get("outline_id") is not None:
+                public_id(public_id(public["outline_id"]))
             for key in ("hard_dependencies", "soft_dependencies"):
                 public[key] = [public_id(value) for value in public.get(key, [])]
             public_books.append(public)
@@ -346,7 +347,7 @@ def book_wiki_series_manifest(project_id: str) -> dict:
     legacy["books"] = [{"book_id": None, "required": True,
                          "status": legacy["status"], "outline_id": None,
                          "hard_dependencies": [], "soft_dependencies": []}]
-    legacy["release_id"] = manifest.get("run_id")
+    legacy["release_id"] = None
     return legacy
 
 
diff --git a/tests/test_kc/test_book_series_manifest.py b/tests/test_kc/test_book_series_manifest.py
index 31b10282..c3b50656 100644
--- a/tests/test_kc/test_book_series_manifest.py
+++ b/tests/test_kc/test_book_series_manifest.py
@@ -19,8 +19,10 @@ def book(book_id="a", status="ready", required=True, release_id="r1", **extra):
 
 
 def series(status="ready", books=None, release_id="r1"):
-    return {"schema_version": SCHEMA_VERSION, "series_id": "s", "release_id": release_id,
-            "status": status, "books": books if books is not None else [book()]}
+    payload = {"schema_version": SCHEMA_VERSION, "series_id": "s", "release_id": release_id,
+               "status": status, "books": books if books is not None else [book()]}
+    payload["manifest_sha256"] = canonical_digest(payload)
+    return payload
 
 
 def test_valid_manifest_roundtrip_and_canonical_digest_does_not_self_reference():
@@ -33,6 +35,8 @@ def test_valid_manifest_roundtrip_and_canonical_digest_does_not_self_reference()
 def test_schema_and_state_transition_fail_closed():
     assert validate_series_manifest(series())["ok"]
     assert validate_series_manifest({"schema_version": "outline-v1"})["ok"] is False
+    missing_digest = series(); missing_digest.pop("manifest_sha256")
+    assert validate_series_manifest(missing_digest)["ok"] is False
     assert transition_status("draft", "partial") == "partial"
     with pytest.raises(ValueError):
         transition_status("ready", "partial")
@@ -52,14 +56,26 @@ def test_hashes_and_dependencies():
     manifest = {"files": {p.name: digest}}
     assert validate_release_files(manifest, p.parent)["ok"]
     assert validate_release_files({"files": {p.name: "bad"}}, p.parent)["ok"] is False
+    assert validate_release_files({"files": {"nested/" + p.name: digest}}, p.parent)["ok"] is False
     books = [book("a", "ready", hard_dependencies=["b"]), book("b", "ready")]
     assert dependency_report(books)["ok"]
+    cross_release = [book("a", "ready", hard_dependencies=["b"], release_id="r1"), book("b", "ready", release_id="r2")]
+    assert validate_series_manifest(series("ready", cross_release))["ok"] is False
     assert dependency_report([book("a", "ready", hard_dependencies=["missing"])])["ok"] is False
     assert dependency_report([book("a", "ready", hard_dependencies=[""])])["ok"] is False
     assert dependency_report([book("a", "ready", soft_dependencies=["missing"])][0:])["soft_missing"] == ["missing"]
 
 
 def test_legacy_manifest_is_single_book_without_guessed_series_membership():
-    result = read_legacy_manifest({"schema_version": "outline-v1", "run_id": "old"})
+    result = read_legacy_manifest({"schema_version": "outline-v1", "run_id": "old", "status": "partial"})
     assert result["legacy"] is True
     assert result["series_id"] is None and result["book_id"] is None
+    assert result["status"] == "partial"
+    assert read_legacy_manifest({"schema_version": SCHEMA_VERSION, "status": "ready"})["legacy"]
+
+
+def test_nullable_outline_id_is_valid():
+    payload = series()
+    payload["books"][0]["outline_id"] = None
+    payload["manifest_sha256"] = canonical_digest(payload)
+    assert validate_series_manifest(payload)["ok"]
```
