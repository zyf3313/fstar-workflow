# Acceptance criteria — Magpie hand-over prune

Source: uTools note/1795525324268 title 「fstar 缺陷报告 hand-over 删除无法传播」, core mechanism verified against source 2026-11-24. User approved proposed treatment (建议 A+B+D, 建议 E optional; 建议 C out of scope) with 「按照你的建议来就行」.

Baseline: branch fix/repro-0111-followup at 9e980e1 plus both workers' incomplete changes. The two original dispatches overlapped on installer.py, its tests, README and the manifest; the claimed parallel partition did not hold. Recovery serializes edits to shared files and preserves both workers' changes.

<!-- A-001:start -->
## A-001 — Stale hand-over reconciliation
Judgment: machine.
route_skills (and install/update paths that call it) must reconcile the ledger against the current bundle: skills recorded as handed_over but absent from the current bundle are surfaced as stale in results. Reconciliation runs in both dry-run (reported as pending removal) and apply modes. Magpie-absent / native-only runs report stale entries informationally without attempting removal, consistent with existing informational actions. The reconciliation must not consider skills the ledger never recorded.
<!-- A-001:end -->

<!-- A-002:start -->
## A-002 — Guarded removal via public Magpie CLI
Judgment: machine.
When a stale handed-over skill is confirmed, removal goes through the public `magpie library skill rm <name>` API (listed by the locally observed Magpie 0.1.4722 help; other versions require capability verification). Removal requires ALL: ledger records library state handed_over, library-side content fingerprint matches the recorded sha256 (user-modified content is never deleted), and the skill name matches an fstar-managed prefix/history. Any failing condition reports stale_but_modified (or a precise reason) without deletion and without blocking the rest of the update. Failed rm calls report prune_failed with the CLI output and never partially mutate the ledger. Successful prune removes the ledger entry and reports pruned_from_library.
<!-- A-002:end -->

<!-- A-003:start -->
## A-003 — Comment accuracy
Judgment: machine.
All four stale 「no verified public removal API」 comments (magpie.py ×3 as reported, installer.py ×1) are corrected to describe the actual behavior: the public rm API exists and is used under the A-002 guards. No comment claims unverified capability.
<!-- A-003:end -->

<!-- A-004:start -->
## A-004 — doctor linkage
Judgment: machine.
When doctor reports RESOURCE_EXTRA for a skill absent from the current inventory, the diagnostic notes whether that skill is still handed over (with agent count when cheaply available) and points to the update path that prunes it. Implementation must not degrade existing doctor output for unrelated entries.
<!-- A-004:end -->

## Verification gates
- New tests cover: stale detection in dry-run and apply; guarded removal success; user-modified library content preserved; non-fstar skill untouched; rm failure reported not swallowed; ledger not mutated on failure; native-only informational behavior. Tests use a fake magpie runner (existing pattern in test suite) — no real library mutation in tests.
- resources/package-assets.json rebuilt if src changes; full python + node suites pass.
- README gains a short accurate paragraph on the prune behavior if user-visible.
- Independent check; no release, push or publish in this task.

## Out of scope
- 建议 C (Magpie-side source recording) — cross-project.
- Executing the manual cleanup of the local fstar-doc library copy (user-side decision, separate from code).
- Any file owned by the parallel repro-0111-followup worker.
