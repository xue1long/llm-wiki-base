# Content readiness golden fixtures

`golden.json` freezes the labels, reason codes, decisions, content kinds, and
audit keys shared by the readiness implementation and its acceptance tests.

The manifest describes deterministic cases rather than source-specific rules.
Concrete text and format fixtures are created by the tests that exercise each
profile; no fixture may rely on a filename to decide readiness.
