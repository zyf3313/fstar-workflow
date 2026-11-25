# Plan — worktree project identity and knowledge resolution

Goal: close the two source-verified worktree gaps from uTools note/1795529117950 without changing healthy sharing behavior. Criteria in criteria.md (A-001..A-004). No release in scope.

## W-1 — Init guard for linked worktrees (A-001)
- Purpose: stop the silent identity split at its trigger.
- Inputs: criteria A-001; `project.initialize_project`/`_initialize_user_directory`; `store._linked_worktree_main_root`/`_initialized_at`; existing storage-mode tests.
- Actions: in `initialize_project`, before creating any identity, detect a linked worktree whose main root `_initialized_at` is true; default: raise a clear InitError naming the shared main root; add the explicit opt-in path and record it in the result. Keep main-tree re-init and non-linked init untouched.
- Outputs: bounded project.py changes + temp-git-worktree tests (refuse default, opt-in allowed, main re-init unchanged).
- Completion: A-001 covered by tests in both user-directory and in-repo main modes.
- Blocked handling: if the opt-in flag surface needs a CLI decision (name/position), pick the documented CLI convention and note it; do not block.
- Dependencies: none.

## W-2 — Learn bridge resolution + error guidance (A-002, A-004)
- Purpose: healthy worktrees share the main data root for knowledge reads/writes; errors stop steering into the trap.
- Inputs: `learn_bridge._read/_prepare/_apply`; `knowledge._require_initialized_project`/`_project_data_root`; `store.find_project_root`.
- Actions: resolve the caller-supplied project_root through `find_project_root` semantics (worktree→main) before the initialized check; explicit `--project`/direct main-root usage keeps current behavior; improve the knowledge_invalid_schema message for unresolvable roots per A-004.
- Outputs: learn_bridge/knowledge changes + tests: read/prepare from a healthy linked worktree succeeds against the main data root; unresolvable root message quality; no worktree mutation.
- Completion: A-002 and A-004 covered.
- Blocked handling: if find_project_root cannot be reused directly (signature/layout), use its helpers; never duplicate the pointer-safety rules.
- Dependencies: none (parallel-safe with W-1; different files).

## W-3 — Doctor split-pointer report (A-003)
- Purpose: make the split state visible and actionable, report-only.
- Inputs: `project.doctor_worktree_report`; `store.worktree_shared_main_root`/pointer readers; criteria A-003.
- Actions: extend the doctor worktree entry to report the split case (worktree pointer data root ≠ main data root) with recovery guidance; keep the shared-healthy case output unchanged; doctor never deletes or rewrites anything.
- Outputs: doctor entry + tests: shared healthy unchanged; split reported with both roots and guidance; main worktree untouched.
- Completion: A-003 covered.
- Blocked handling: unreadable pointer records surface as "unreadable", not a crash.
- Dependencies: none (parallel-safe with W-1/W-2; doctor assembly only).

## W-4 — Integration verification
- Purpose: verify all criteria together and the two-layer impact.
- Inputs: worker delivery; real temp git worktrees.
- Actions: rebuild manifest; full Python + Node suites; independent checker runs adversarial probes: explicit --project override, non-worktree regression, user-directory and in-repo main modes, pointer-safety (no silent fallback) preserved.
- Outputs: checks report; awaiting_acceptance only when all criteria hold.
- Blocked handling: any failed criterion returns to implement before check.
- Dependencies: W-1..W-3.
