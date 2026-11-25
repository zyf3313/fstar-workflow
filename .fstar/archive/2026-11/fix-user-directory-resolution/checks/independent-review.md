# Independent review: user-directory resolution

Checker: fstar-check a202d8deb99da0970, distinct from implementer a40792ba2550dae35. Initial independent review reproduced two defects in the first delivery: an unusable pointer in a linked worktree could be bypassed by main-root fallback; a non-UTF-8 pointer raised UnicodeDecodeError instead of corrupt_pointer. The first review failed A-002 and A-003.

The implementer subsequently changed `store.py` and added worktree regressions. They report 66 targeted tests passed, including bridge writes, user-directory linked worktrees, broken pointers and shared/local compatibility. The independent recheck passed both pointer repairs and 26 targeted tests, but failed documentation: a tracked `.fstar` can make the linked worktree locally initialized and take precedence over main-root fallback. README was corrected and the checker confirmed its wording in a bounded recheck. After repair the coordinator ran the canonical Python suite: 992 tests passed in 118.755s; the Node package suite passed 16 tests. The checker states that its bounded final recheck is not a fresh complete A-001–A-004 final check.

The changed behavior deliberately prevents fallback for an unusable direct pointer across all three storage modes, rather than silently selecting the main project's identity. Worktrees without a direct pointer still use the initialized main project.

This is a factual interim record, not acceptance. Task start was later recorded (2026-11-23T13:11:29Z) with the user's same-day request to proceed with merge and release as the conversation source. Recovery authorization for this task remains pending; no confirmation was recorded before then.
