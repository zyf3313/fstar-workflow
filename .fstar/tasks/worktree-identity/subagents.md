# Native worker handoffs — worktree-identity

## implement — 8f57359d-e5a9-4fb8-94a5-73903f5fb4f5
- Baseline: main d310863 (0.11.2), branch feat/worktree-identity; payload /tmp/fstar-worktree-identity-payload.json with delivery baseline recorded there.
- Scope: src/fstar/{project,store,knowledge,learn_bridge}.py, tests (test_storage_modes, test_project, new test_worktree_identity, test_knowledge, test_learn_bridge), README, manifest — steps W-1..W-3.
- Required: real `git worktree add` fixtures only (no fake gitdir); A-001 init guard with explicit opt-in; A-002 learn bridge resolves via find_project_root semantics; A-004 error guidance; A-003 doctor split-pointer report (report-only).
- Completion: focused worktree tests + suite green after manifest rebuild; result JSON with dispatch identity preserved.
- Status: implementation returned; full suite 1056 Python and 16 Node tests reported passing, but independent check failed.

## check — 79ffba05-4c70-4dc7-95e5-459f70b22548
- Status: failed: tracked project-shared worktree re-init is rejected, force-separate reports success without distinct identity, corrupt worktree pointer loses its specific error. Checker reproduced against baseline in /tmp/fstar-check-79ff/; no report file was produced. Full suite alone did not cover these scenarios.

## implement repair — 5cdecfe3-2c6f-41df-bc9d-a57beb1ac192
- Baseline payload: /tmp/fstar-worktree-repair-payload.json; delivery digest 4182d7caf00e1e2c90d70d2fbed48e2d7e33518a84e82c597026095e4b0463b3. Scope: payload paths; prior failure is the independent check above.
- Required: investigate and fix verified regressions, preserve user data and honest distinct-identity semantics, add real linked-worktree regression tests, rebuild manifest, then fresh independent check.
- Status: blocked after partial repair; tracked shared worktree re-init preserved and force-separate on existing metadata refuses without mutation. Specific corrupt-pointer CLI diagnostic remains unresolved because CLI/installer were outside scope. Focused 44 Python tests, full 1057 Python tests and 16 Node tests passed; a ResourceWarning was reported.

## implement diagnostic repair — 272d06a5-0aeb-4873-b493-f2508c71c960
- Payload: /tmp/fstar-worktree-diagnostic-payload.json; current delivery digest d4a589e00e771ce36e6d3b13a750688d15d74fa1e18d5af982fd84dd0d0b0a82. Scope expands to CLI/installer and tests to restore error specificity while preserving doctor reporting and no-fallback behavior.
- Completion: real worktree probes, focused tests, manifest rebuild and impact review; follow with a fresh independent check.
- Status: implementation returned: strict pointer diagnostics restored for normal CLI; doctor keeps read-only reporting. Worker reported 189 focused tests, 13 worktree tests after the final fixture change, and 16 Node tests passing; manifest rebuilt. Full Python suite and independent check on the final snapshot remain pending.

## check — ac4285aa-1476-4396-b47c-2e012c70cd24
- Payload: /tmp/fstar-worktree-check-payload-v2.json; delivery digest 5d8470fbc49c18aeba6362aec71b60df2277a0b04dd7f3d57d9eb716b8b9b760. Scope: read-only independent review of A-001..A-004 and prior failures.
- Status: failed independent check. The checker reproduced a valid worktree-bound pointer with a different data root: doctor reports split, but find_project_root returns the worktree, contrary to literal A-003. This conflicts with A-001's working explicit separate-identity path and preservation of existing identities. A-001's treatment of force-separate when an identity already exists is also not explicit: implementation safely refuses without mutation. Prior three regressions rechecked successfully. Checker verified all listed file hashes before and after, manifest asset hashes, and 44 focused tests; full delivery digest and criterion-item hashes were not independently recomputed. Evidence: /tmp/fstar-check-ac4285-probe.py, /tmp/fstar-check-ac4285-probe.log, /tmp/fstar-check-ac4285-focused.log. No official check record was produced.
- Coordinator full Python regression on this snapshot: 1057 tests passed; ResourceWarning for an unclosed temporary project.lock. Node: coordinator independently observed 16 tests passed.
- 2026-11-25: user selected 「授权本任务恢复（推荐）」 for recovery and rechecking under the stated separate-identity boundary; the original overbroad A-003 was corrected along with the A-001 existing-metadata edge case. The failed check is retained as historical evidence, not relabeled as passed.

## check — 1641d14d-29ae-4832-a0f6-86ff7db94ad5
- Original temporary payload was accidentally overwritten during the next dispatch; the original fingerprints are retained in the check result/evidence listed below. Original delivery digest 5d8470fbc49c18aeba6362aec71b60df2277a0b04dd7f3d57d9eb716b8b9b760. Scope: read-only review of corrected A-001..A-004, prior findings and caller impact.
- Status: failed by distinct native fstar-check. A-001, A-002 and A-004 passed; A-003 failed because a structurally valid pointer bound elsewhere yields generic project_not_initialized, and doctor recovery guidance omits that migration requires confirmation and rebinding does not merge data. Checker verified actual input/item/delivery fingerprints, all 63 manifest hashes and 13 focused tests. Genuine result /tmp/fstar-worktree-check-final-1641-result.json and evidence /tmp/fstar-worktree-check-final-1641-evidence.json; probe /tmp/fstar-final-probe-1641.py. Failure harvested; repair and a fresh independent check are required.

## implement repair — 5c0d78fe-40cb-4c7a-8078-c92465ae8dc2
- Payload /tmp/fstar-worktree-last-repair.json; delivery digest 40c041b81e7c67a5bc21ef375fafefda21ec9a5e310404e32153af432f7c6187; prior failure 1641d14d-29ae-4832-a0f6-86ff7db94ad5. Scope limited to pointer diagnostics, doctor guidance, relevant tests, README and manifest.
- Status: done and harvested as evidence 92b8af0d-ed72-49a4-9c01-afc8084dcc96. Worker reported both prior probe failures fixed, 44 focused tests passed and manifest rebuilt; full suites and fresh check pending.

## check — 5ed2fd2f-9be1-4617-8114-4d537e714ba5
- Payload /tmp/fstar-worktree-check-final.json; delivery digest c136e4af83a964ecc768b64854d129a1c489be7c5a7b1ba8b45f87283b8146ab; scope read-only A-001..A-004 and previous failures.
- Status: passed by independent native fstar-check; A-001..A-004 and both prior failures checked with real temporary worktrees, 44 focused tests and all 63 manifest hashes; actual snapshots matched before and after. Result /tmp/fstar-worktree-check-final-5ed2-result.json, evidence /tmp/fstar-worktree-check-final-5ed2-evidence.json; harvested evidence adec92c0-c95c-4d16-bd65-3f991399f9d7. Coordinator observed Python 1057 tests and Node 16 tests passing; Python emitted an unclosed temporary lock ResourceWarning.
