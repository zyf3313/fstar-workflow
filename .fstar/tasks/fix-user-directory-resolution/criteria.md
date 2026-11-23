# Fix user-directory project resolution gaps: acceptance criteria

Source: user request 2026-11-23 "修复下Utools 中markdown 下 fstar 工作流有个问题……首先需要确定的问题 其次确认是否是通用硬伤问题 而不是某个工具所影响的", against the uTools note "fstar+herdr+magpie 落地：实测问题与方法论沉淀方案" (note/1795418865533). Both problems were reproduced in this repository before the task was opened, so the criteria describe the target behaviour, not a guess.

Reproduction recorded by the coordinator (temporary user root, real CLI):
- `fstar --user-data-root <U> init <P> --storage user-directory` succeeds; the project directory holds only `.fstar-pointer.json`; the schema marker lives at `<U>/projects/<uuid>-<name>/.schema-version`.
- `knowledge._require_initialized_project(<P>)` fails with `knowledge_invalid_schema: Project writes require an initialized project (schema 1)`, while `_require_initialized_project(<P>, data_root=catalog.data_root)` succeeds — so the learn bridge's pre-check is the only pointer-blind gate.
- `find_project_root(<linked worktree of <P>>)` returns `None`; the main project root resolves fine.

All criteria are machine-verifiable.

<!-- fstar:item:A-001:start -->
### A-001 Learn bridge accepts pointer-resolved projects

- 判定方式：machine
- The learn bridge's `prepare` and `apply` paths succeed for a user-directory project (pointer file, data root in the user root) exactly as they do for a project-shared project: the initialization pre-check resolves the pointer's data root, and a proposal can be prepared and applied. An uninitialized project is still refused with the documented error (`knowledge_invalid_schema`, "Project writes require an initialized project (schema 1)"), and a nonexistent project root is still refused; the existing error codes, messages and details are not weakened.
- 检查方法：new regression test that initializes a temporary user-directory project (CLI-level or store level), drives the bridge request/response protocol for a user-level rule write and a project-level write, and asserts success plus the still-refused cases for an uninitialized and a nonexistent project.
<!-- fstar:item:A-001:end -->

<!-- fstar:item:A-002:start -->
### A-002 Linked worktree of a user-directory project resolves

- 判定方式：machine
- `find_project_root` inside a linked git worktree of a user-directory main repository returns the initialized main project root, so fstar commands run in the worktree stop reporting "not an initialized project" without any hand-copied pointer file. A worktree that carries its own pointer keeps resolving through it. Project-shared and project-local worktrees without an unusable local pointer, ordinary directories, and worktrees of an uninitialized repository keep their current resolution (including `None`). An unusable local pointer in a linked worktree blocks fallback in every storage mode to avoid silently selecting another project.
- 检查方法：new regression test that creates a git repository, initializes it with `--storage user-directory`, adds a linked worktree and asserts the resolution from the worktree directory; plus the unchanged project-shared worktree case and the uninitialized case. The existing test `tests/test_worktree_shared_root.py::ModeRegressionTests::test_user_directory_mode_unaffected_by_worktrees`, which asserts the current `None` result for a user-directory worktree, encodes the old behaviour and is updated to the new expectation with its rationale recorded.
<!-- fstar:item:A-002:end -->

<!-- fstar:item:A-003:start -->
### A-003 No regression in the surrounding mechanisms

- 判定方式：machine
- The full Python and Node suites pass. Existing user-directory behaviour (pointer reading, rebind, project config layering, runtime slot keying, knowledge catalog data root) is unchanged. Project-shared/project-local behavior remains unchanged except that a linked worktree's unusable local pointer now blocks fallback, preventing an unintended project identity switch. The change does not relax pointer safety: a corrupt, symlinked or path-mismatched pointer is still refused rather than followed, and a moved project still requires an explicit rebind.
- 检查方法：full test suite plus targeted tests over the pointer and layout helpers, including the corrupt/moved-pointer cases.
<!-- fstar:item:A-003:end -->

<!-- fstar:item:A-004:start -->
### A-004 Delivery, documentation and scope

- 判定方式：machine
- The change is limited to the project-resolution paths it needs (no unrelated refactoring, no schema migration, no change to acceptance semantics, evidence validation or routing hard rules). README and the packaged skills describe the fixed behaviour wherever they currently state the old limitation. No npm publication (the user's responsibility) and no change to real host configuration or the user's real `~/.fstar` data.
- 检查方法：diff review against the baseline commit, README/skill text review, and the independent final check.
<!-- fstar:item:A-004:end -->
