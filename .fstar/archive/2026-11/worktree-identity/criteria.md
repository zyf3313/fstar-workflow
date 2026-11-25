# Acceptance criteria — worktree project identity and knowledge resolution

Source: uTools note/1795529117950 (「fstar worktree 规范沉淀归属 验证与缺陷」, 2026-11-24), mechanism verified against source 2026-11-25: `store.find_project_root`/`_linked_worktree_main_root`, `knowledge._require_initialized_project`, `learn_bridge._prepare`/`_read`/`apply_change`, `project.initialize_project`. User directed this scope with 「归档吧 开工另外个任务」. On 2026-11-25, after the independent check identified the A-001/A-003 conflict, the user selected 「授权本任务恢复（推荐）」 for recovery and rechecking under the stated separate-identity boundary. A-001/A-003 below correct the original overbroad pointer assertion; they do not claim the user separately reviewed every individual criterion. Baseline: main 0.11.2 (d310863 archive commit). No release/publish in this task (release is a separate user action).

<!-- A-001:start -->
## A-001 — Linked-worktree init guard
Judgment: machine.
Running `fstar init` inside a linked git worktree whose main worktree is already an initialized fstar project must NOT silently create a second project identity. With no existing local identity, default behavior refuses with a clear error naming the shared main root and its data root, plus guidance for the explicit opt-in (`--force-separate`); the opt-in creates and records a normal separate identity. When local metadata already exists, forced separation refuses without modifying it rather than claiming a new identity was created; ordinary re-init preserves an existing initialized identity and its storage mode. Main worktree re-init and standalone (non-linked) directory init keep current behavior.
<!-- A-001:end -->

<!-- A-002:start -->
## A-002 — Learn bridge resolves the project root like the CLI
Judgment: machine.
The learn bridge (`read`, `prepare`, `apply`) must resolve the caller-supplied `project_root` through the same worktree→main resolution the CLI uses (`find_project_root`), so that a healthy linked worktree passes the initialized-project check against the main data root instead of failing with knowledge_invalid_schema and steering the user into re-initializing (A-001's trap). Explicit `--project` overrides in the CLI path keep their current behavior (override wins). Resolution is read-only and never mutates the worktree.
<!-- A-002:end -->

<!-- A-003:start -->
## A-003 — Stale worktree pointer is a diagnosable state, not a trap
Judgment: machine.
A valid initialized identity correctly bound to a linked worktree resolves to that worktree even when its pointer's data root differs from the main root; `fstar doctor` reports that difference as split without assuming it was accidental. For an unusable local pointer, resolution never silently falls back to the main project or an initialized ancestor; normal CLI commands retain the specific pointer error and doctor reports the problem read-only. Doctor reports the worktree path and the main and recorded data roots when available, with data-preserving recovery guidance; it never deletes or rewrites anything. A worktree pointer that matches the main root is reported as shared and healthy. Pointer removal or data migration requires user confirmation; rebinding does not merge data.
<!-- A-003:end -->

<!-- A-004:start -->
## A-004 — Uninitialized-worktree learn error points to the resolution, not the trap
Judgment: machine.
When a project write is attempted from an uninitialized directory, the knowledge_invalid_schema guidance must not imply "run init here" for a linked worktree of an initialized main: it names the main root it resolved to when resolution succeeds, and when the caller supplied an unresolvable root it states that directly. The A-002 fix removes the false positive for healthy worktrees; this criterion covers the message quality for the remaining genuine cases.
<!-- A-004:end -->

## Verification gates
- All scenarios exercised in temp git repos with real `git worktree add` (no fake gitdir), covering: healthy sharing, init in linked worktree (refuse + opt-in), learn read/prepare from a linked worktree, split-pointer doctor report, uninitialized directory error.
- Suites: `PYTHONPATH=src python3 -m unittest discover -s tests -t .` and `node --test tests/test_package.cjs`; manifest rebuilt after src changes.
- README updated for user-visible behavior (init guard, learn resolution, doctor entry).
- Independent check distinct from the implementer; adversarial probes incl. explicit --project override and non-worktree regression.
- No invented evidence; this task does not change evidence mechanics, but evidence freshness rules still apply to the final check.

## Out of scope
- `fstar worktree-heal` / automatic merge of a split worktree project into the main root (user data migration; report-only in this task).
- Real worktrees on this machine (report referenced other projects; only temp fixtures are touched).
- Deleting any pointer file on the user's real repositories.
