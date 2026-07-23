# Task 4 Audit Fix Report

- Implemented URL-specific collector flow that performs READ permission enforcement and SSRF ACL validation before the network request.
- URL content is written directly to the collector processing raw path; `move_to_processing` remains file-only.
- Added public-address validation using `socket.gethostbyname` and `ipaddress`; private, loopback, link-local, and DNS failures raise `PermissionDenied`.
- Added HTTP redirect following and URL permission handling.
- Kept the ACL helper in `src/pipeline/collector.py` because it is specific to the collector's network boundary; generic path permission hardening remains assigned to Task 9.
- Verification: 5 URL collector tests passed; 16 pipeline regression tests passed. The requested `tests/test_permissions` path does not exist in this checkout.
