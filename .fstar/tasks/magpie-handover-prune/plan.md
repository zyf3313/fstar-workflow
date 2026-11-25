# Plan — Magpie hand-over prune

Goal: close the delete-direction gap of the Magpie hand-over (only-additive ledger). Criteria in criteria.md (A-001..A-004); source note verified. Recovery serializes shared-file work with repro-0111-followup; the original dispatches overlapped.

## Step P-1 — Reconcile + guarded prune in magpie.py
- Purpose: A-001 + A-002 + A-003.
- Inputs: criteria.md; magpie.py route_skills/_load_record/_library_state/uninstall_local; existing fake-runner tests; the reporting report from uTools note/1795525324268 (evidence, not authority).
- Actions: extend route_skills to reconcile ledger ∪ bundle; add guarded removal via runner invoking the public `library skill rm`; dry-run reports pending; failure paths report without mutating ledger; correct the stale comments in place.
- Outputs: bounded magpie.py changes + tests (fake runner only).
- Completion: A-001, A-002, A-003 proven by tests.
- Blocked handling: if the magpie CLI contract cannot be verified locally, implement behind the existing runner seam and report the verification limitation; never guess CLI output formats.
- Dependencies: none on the parallel task; magpie.py/installer.py only.

## Step P-2 — Wire install/update/uninstall reporting + doctor hint
- Purpose: A-004 and end-user visibility.
- Inputs: installer.py update/uninstall result assembly; doctor diagnostics assembly.
- Actions: surface stale/prune results in update output; doctor RESOURCE_EXTRA entries gain the handed-over hint when ledger data supports it.
- Outputs: installer.py changes + focused tests.
- Completion: A-004 proven; existing doctor output byte-identical for unrelated entries.
- Blocked handling: if the hint cannot be computed cheaply, report stale entries without agent counts rather than adding expensive scans.
- Dependencies: after P-1 (needs the ledger reconciliation helpers).

## Step P-3 — Independent verification
- Purpose: verify all criteria + parallel-safety.
- Inputs: worker delivery; git diff confined to magpie.py/installer.py/tests/shared bookkeeping.
- Actions: rebuild manifest; full suites; independent checker reviews the combined shared-file changes and runs adversarial fake-runner probes.
- Completion: all criteria evidenced; combined impact assessed; report in checks/.
- Blocked handling: unresolved shared-file conflicts or unsafe behavior return to repair before check.
- Dependencies: P-1, P-2.
