# Release readiness check

Checker: fstar-check ab3955bb6c2a91238, dispatch release-readiness-check-001, read-only, 2026-11-23. Baseline HEAD 2c86f0f plus working tree; all fingerprints stable before and after.

## Result

One reproducible release blocker; everything else passing.

### Blocker

`resource_version` stays "9" while resource content changed (fstar-doc removed, 63 files vs 64, routing/skill text changed). `plan_install(operation="update")` from a materialized 0.10.1 bundle fails with `resource_version_conflict` because version directories are immutable (installer.py:697, :422). Every real 0.10.x install would fail `fstar update`. Convention: resource_version bumped 8→9 exactly when 0.9.0→0.10.0 changed content.

Fix on the release branch: package.json version + fstar.cli_version → 0.11.0, fstar.resource_version → "10", rebuild package-assets.json.

### Verified passing

- fstar-doc retirement: zero stale references; 10 skills; installer EXPECTED_COUNTS skills 10; manifest 63/63 hashes match, no fstar-doc entries; retirement pass covered by tests/test_doc_retirement.py; checklist reference intact.
- User-directory resolution: learn_bridge pointer-aware pre-check; store worktree fallback follows main pointer, blocks unusable local pointers across all modes, non-UTF-8 pointers → corrupt_pointer; README worktree section matches behavior; old test updated with rationale.
- Prior findings resolved: custom-grant routing contradiction and stale skill count fixed.
- Full canonical suites: Python 992 OK (twice), Node 16 OK; targeted 20 + adjacent 99 tests OK.

### Scope gaps

No real previous-version installation or live host variant exercised (temp roots only). Host-local ~/.claude fstar-doc copy is a git-ignored install artifact retired by the update path. `src/fstar/__init__.py __version__ = "0.1.0"` predates this delivery and gates nothing. npm publish not attempted (user's responsibility).
