# Final independent read-only check

Checker: fstar-check instance aaae28549ca477197, distinct from implementer a105248821c92857b. Dispatch external-upgrade-final-001, allowed_paths=[], no writes. Coordinator persisted this report from the checker's returned findings. Baseline: delivery-baseline.json; all four hashes verified unchanged before and after independent review.

| Criterion | Verdict | Evidence |
|---|---|---|
| A-001 | passed | update-only discovery includes recorded external roots, including reuse-only roots. `_plan_host_files` selects upgrade_external for consistent unchanged records. New default-update regression exercises no owned host files. |
| A-002 | passed | Identity, historical version and hash checked; modified/unrecorded/inconsistent external files remain conflicts even with overwrite/new. Symlink targets refused. External-root discovery is update-only; uninstall and stale-file deletion still require ownership. Selected-root boundaries and mismatch refusal retained. |
| A-003 | passed | Reverify refuses plan/apply drift; write path uses source integrity, ancestor checks, backup, journal and atomic write. Manifest and entry index update to current hash/version/ownership. Later update is idempotent and later user edits protected. Owned overwrite index consistency also covered. |
| A-004 | passed | Full Python 972 OK, Node 16/16; real subprocess exit codes both 0. Manifest rebuilt twice in isolated copy with unchanged hash. README matches behavior. No unrelated hooks/schema/acceptance changes or npm publication. |

## Verification provenance

- Coordinator executed full Python and Node suites: [regression.json](regression.json), [python.log](python.log), [node.log](node.log). Python 116.718 seconds (972 tests); Node 16 tests. Checker incorporated these results and independently reviewed code and all 17 new regression cases; did not duplicate full test runs.
- Actual build idempotence: [manifest.json](manifest.json), two builds in a temporary copy; sha256 ab3e3932702fa0cd67331f82b5bf049b5382f5451d7fd37d5b1d7783aacd5da4.
- All new tests use temporary roots. No real host configuration writes by tests or checker.

## Two-layer impact review

1. CodeGraph impact: changed/new helper signatures are internal to installer.py; existing callers remain compatible. `_manifest_owned_roots` retains its signature through `_recorded_roots`.
2. Mechanism interactions: update target discovery, selected-root filtering, overwrite/conflict policy, uninstall isolation, plan/apply staleness, backup/journal rollback, manifest, entry index and doctor paths reviewed. No task events, evidence semantics, context budgets or schema migration changes. Index now follows both upgrade_external and ordinary owned overwrite rather than retaining stale ownership/version metadata.

## Delivery hashes

- src/fstar/installer.py: 64a0f3b6faa112182e03b7efd5c16dfab4b2ed61b42e31bf7c685ccd2d0d9c0f
- tests/test_external_host_upgrade.py: d4ed200b772b5500c9f51097251412b36894f9c1d8924f6e8d8bf1cc4113e109
- README.md: 592709b9cc48f5dc9a67169eaf3c76daaf6daa4453ab01d45edb12d7482ba5fa
- resources/package-assets.json: ab3e3932702fa0cd67331f82b5bf049b5382f5451d7fd37d5b1d7783aacd5da4

Defects found: none. Blockers: none. The reviewer noted a pre-existing same-name external-backup collision within one transaction; existing journal-based rollback remains unchanged. This report does not claim npm publication or broad live-host validation.
