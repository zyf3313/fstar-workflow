# Plan — verified 0.11.1 follow-up

Goal: complete the verified fixes in criteria.md with supported end-to-end behavior. The uTools note supplies reproduction hypotheses, not authority to weaken validation. See criteria.md for requirements and source; no separate clarify document is necessary because the user approved the bounded proposal.

## P-001 — Repair deliverable mapping
- Purpose: cover A-001.
- Inputs: criteria.md, tasks.register_deliverable, EvidenceService snapshots/current-check validation and existing map tests.
- Actions: establish compatible per-artifact whole-file mapping for ordinary deliverables while preserving explicit item mappings; trace snapshot/validation/invalidation/dependency consumers. Supply a real CLI-based evidence chain fixture.
- Outputs: bounded core changes, end-to-end regression, accurate README explanation.
- Completion: A-001 satisfied including invalidation and checker independence.
- Blocked handling: report incompatible historical mapping assumptions; do not switch an entire mixed map to global file mode or bypass scope checks.
- Dependencies and adjustment: foundational for later check evidence; choose representation based on existing contracts, document compatibility decisions.

## P-002 — Reconcile installer symlink handling
- Purpose: cover A-002.
- Inputs: isolated symlink reproduction and installer ownership/backup/path validation.
- Actions: align dry-run and apply for native skill links; preserve external target contents, distinguish safe reuse from explicit managed replacement and user-conflict preservation; test real install/update and rollback boundaries.
- Outputs: installer changes and focused integration tests.
- Completion: A-002 satisfied, with default and native-only behavior tested.
- Blocked handling: do not remove arbitrary user links or disable root confinement; return unsupported cases with truthful diagnostics.
- Dependencies and adjustment: independent code area, implemented sequentially by the assigned worker.

## P-003 — Stable dispatch identities
- Purpose: cover A-003.
- Inputs: DispatchService.register, harvest, reservations, lease lifecycle, compact_events.
- Actions: add bounded canonical identity/replay handling under the task transaction; reject divergent payload reuse; define interrupted/terminal/lease-expiry behavior and safe legacy fallback.
- Outputs: dispatch changes and regression coverage.
- Completion: A-003 satisfied, same payload repeated four times results in one registration event.
- Blocked handling: preserve conflict guards and original evidence, never reconstruct a fake worker result.
- Dependencies and adjustment: use current artifact-map semantics from P-001 when fingerprinting inputs.

## P-004 — stdin JSON and cross-project diagnostics
- Purpose: cover A-004 and A-005.
- Inputs: CLI JSON reader, dispatch CLI adapters, task resolver and user project registry.
- Actions: support one stdin JSON document with explicit duplicate-consumer rejection; add read-only registry-scoped missing-task candidates without changing task selection.
- Outputs: CLI/store changes, boundary tests and usage docs.
- Completion: A-004/A-005 satisfied; old path-based calls continue to work.
- Blocked handling: no filesystem-wide scans, no cross-project writes, no hidden stdin reuse.
- Dependencies and adjustment: runs after P-003 so dispatch stdin examples use the final contract.

## P-006 — Evidence schema and documentation
- Purpose: cover A-006, approved in response to the B-11 follow-up.
- Inputs: evidence and dispatch validation implementations and existing schema commands.
- Actions: expose a correct schema example and document baseline/digest semantics and stale-evidence handling.
- Outputs: CLI/schema code, README and meaningful regression tests.
- Completion: A-006 verified against actual validators and hash helpers.
- Blocked handling: report unsupported fields rather than weaken validation or fabricate evidence.
- Dependencies and adjustment: follow core implementation and serialize shared README and manifest changes.

## P-005 — Independent verification and handoff
- Purpose: verify A-001 through A-005 and interaction safety.
- Inputs: worker delivery and canonical content hashes, actual test logs, new/old relevant tests.
- Actions: rebuild package manifest; run full Python/Node suites; independent checker runs adversarial end-to-end probes and impact checks. Any failed criterion returns to implement worker, followed by a fresh check.
- Outputs: checks/final.md, machine evidence with actual report/run identity, final awaiting_acceptance state only when valid.
- Completion: all criteria proven with fresh immutable delivery snapshots; no ignored blockers.
- Blocked handling: retain failed evidence and report limits; never generate random digest values or relabel old checks as new executions.
- Dependencies and adjustment: depends on P-001..P-004. No publication or merge in scope.
