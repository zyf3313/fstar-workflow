# Fix user-directory project resolution gaps: plan

User authorization: 2026-11-23 "修复下Utools 中markdown 下 fstar 工作流有个问题……首先需要确定的问题 其次确认是否是通用硬伤问题 而不是某个工具所影响的" (uTools note note/1795418865533, problems 1 and 2). npm publication stays with the user.

Coordinator reproduction (temporary user root, no real host writes) established that both problems are fstar kernel defects, independent of uTools, herdr or magpie: the learn bridge's pre-check never consults the pointer, and the linked-worktree fallback never consults the pointer. Problem 3 of the note (rule bodies are not injected into the session) is by design — only the index navigation lines are injected — and is not a defect; the user-level procedure limitation is a design constraint of `CATEGORY_DIRS`.

One existing test (`tests/test_worktree_shared_root.py::ModeRegressionTests::test_user_directory_mode_unaffected_by_worktrees`) asserts that a user-directory worktree stays unresolved. That assertion encodes the old behaviour which the note shows to be unusable in practice (a worktree of a user-directory repository is invisible to fstar); the delivery updates it to the new expectation and records why.

<!-- fstar:item:PLAN-1:start -->
1. Implement: (a) `src/fstar/learn_bridge.py` — resolve the project's data root through the pointer before the initialization pre-check, reusing the catalog the bridge already loads, and keep the "uninitialized project" refusal for both uninitialized and nonexistent project roots. (b) `src/fstar/store.py` — extend the linked-worktree fallback in `find_project_root` to follow the main worktree's pointer file (with the same corrupt/symlink/path-mismatch refusals as the in-tree pointer branch). Add targeted regression tests covering both defects and the unchanged project-shared/uninitialized behaviour. Update README and any packaged skill text that states the old limitation.
2. Independent read-only final check covering A-001..A-004 with a two-layer impact review; coordinator runs the full Python and Node suites.
3. Record evidence, delegated acceptance (project rule), archive, merge to main, sync Git. Release preparation (0.11.0, shared with the doc-merge delivery) on a release branch; the user publishes to npm.
<!-- fstar:item:PLAN-1:end -->

Progress: implementation pending.
