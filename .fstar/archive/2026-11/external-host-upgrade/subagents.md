# Dispatch log

## external-upgrade-implement-001

- Native role: fstar-implement; instance: a105248821c92857b.
- Input versions, baseline and exact allowed paths: [implement-payload.json](implement-payload.json).
- Criteria: A-001..A-004, plan: PLAN-1.
- Scope: historical externally reused host file upgrade, default update selection, ownership/index consistency, regression tests and README.
- Completion: targeted validation passes; return actual paths, hashes and evidence. Out-of-scope requirements return blocked.
- State: stopped by coordinator after prolonged execution (about 42 minutes); working changes retained and frozen. Stop notification reported 17 new tests and 972 full-suite passes, but no complete handback artifact, so these are implementation claims only. Coordinator independently captures full regression logs.
- Observed delivery: src/fstar/installer.py, tests/test_external_host_upgrade.py, README.md. Final fingerprints recorded in delivery-baseline.json (also covers manifest). No competing edits.

## external-upgrade-final-001

- Native role: fstar-check; instance: aaae28549ca477197; allowed_paths=[]; read-only.
- Inputs: criteria.md, delivery-baseline.json and the frozen production/test/README diff.
- Criteria: A-001..A-004. Must verify fingerprints before/after, ownership safeguards and both layers of impact. Coordinator runs full Python/Node while checker independently reviews implementation and targeted tests; no concurrent production writes.
- State: running.
