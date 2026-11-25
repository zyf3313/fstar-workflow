# Acceptance criteria — verified 0.11.1 follow-up

Source: user approved the preceding verified findings and proposed priority order with “行” (2026-11-24). Source note: uTools note/1795522260367. Local reproductions: /var/folders/jc/_t2cms2s37g2qgn6rst44x000000gn/T/fstar-0111-verify-xo7ihp0n. Baseline: main 9e980e1, published 0.11.1. No version release, push, merge, status overview or unrelated hook behavior changes in this task.

<!-- A-001:start -->
## A-001 — Usable deliverable evidence mapping
Judgment: machine.
Registering a normal project-relative deliverable must establish a usable evidence mapping, not merely an empty path entry. A real independent check can validate the declared scope and reach awaiting_acceptance using supported registration/dispatch paths without direct task.json repair. Existing item-scoped mappings, dependency/freshness checks and final-check independence remain intact; changes to the delivered file stale earlier evidence. Reject unsafe paths without silently claiming usable evidence scope.
<!-- A-001:end -->

<!-- A-002:start -->
## A-002 — Safe host skill symlink updates
Judgment: machine.
An external directory symlink for a native skill must not make an otherwise reusable installer-owned entry fail only on actual update after a successful preview. Preview and apply share a truthful treatment of identical, stale-owned and user-modified/unowned entries. Never write through a link to an external target; preserve external contents and unrelated user links. Any replacement affects only the explicitly managed link and provides backup/recovery. --native-only continues to skip Magpie hand-over rather than bypass path protection.
<!-- A-002:end -->

<!-- A-003:start -->
## A-003 — Idempotent dispatch registration
Judgment: machine.
An identical persistent dispatch ID/payload retry produces one registration event and returns a coherent existing registration. Reusing an ID with different scope/role/input identity is explicitly rejected without mutation. Lease conflicts, expired/released leases, harvested results, interrupted work and event compaction cannot silently create duplicate or contradictory registrations. Preserve legacy tasks with no new metadata.
<!-- A-003:end -->

<!-- A-004:start -->
## A-004 — JSON stdin input
Judgment: machine.
--payload -, --result -, --confirmation - accept one JSON object from stdin with the same validation/errors as file input. Existing paths remain unchanged. Invalid/empty/non-object input fails without task mutation. Multiple stdin consumers in one invocation produce a clear deterministic error rather than blocking or silently reusing the wrong document. Avoid unrelated CLI surface changes.
<!-- A-004:end -->

<!-- A-005:start -->
## A-005 — Cross-project not-found hints
Judgment: machine.
When a task is absent locally but found in another initialized project known to the configured user registry, task_not_found remains a failure in the selected project and includes read-only candidate project locations and usable --project guidance. Never auto-select or mutate another project. Unavailable/corrupt unrelated projects must not break local lookup. Same-name multiple hits remain explicit candidates; no unrestricted filesystem scan.
<!-- A-005:end -->

<!-- A-006:start -->
## A-006 — Evidence schema and accurate digest guidance
Judgment: machine.
Expose a check-evidence schema/reference via `fstar schema evidence`, with a valid example and useful baseline guidance. Document that delivery.digest is the content hash of the canonical sorted list of path/existence/raw-byte SHA-256 entries, while whole-file item snapshots hash normalized text. Empty result baseline objects are valid. Stale evidence requires appropriate recomputation and rechecking; do not recommend blindly copying actual hashes to expected values.
<!-- A-006:end -->

## Release gates for this delivery
- Tests exercise outcomes above, including a fresh-temp-project CLI delivery → independent check → awaiting_acceptance flow for A-001.
- Python and Node suites pass after rebuilding resources/package-assets.json; README reflects public behavior.
- Independent reviewer checks both callers and interactions (leases, event compaction, artifact freshness, installation ownership/rollback, cross-project isolation).
- No invented check evidence: record real worker outputs and canonical snapshots. This task touches evidence mechanics and is not eligible for acceptance under the standing self-acceptance exemption alone.
