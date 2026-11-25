# Clarification — worktree identity

## Evidence and scope

- User requested the next task: 「归档吧 开工另外个任务」. Source: uTools note `note/1795529117950`; goal is shared knowledge and project identity for healthy worktrees, with explicit opt-in for a separate identity and read-only diagnostics.
- Independent check `ac4285aa-1476-4396-b47c-2e012c70cd24` found that the original A-003 contradicted A-001: a valid distinct identity cannot both resolve locally and always return `None`. The original report's blanket assertion about all worktree pointers was not supported by the source order or real-worktree reproduction.

## Confirmed boundary

- After the coordinator stated the recommendation to preserve valid separate identities, prevent silent fallback for unusable pointers, report split states read-only, and refuse forced separation when metadata already exists, the user requested 「先把当前任务结束了 然后核实下这些问题」 and selected 「授权本任务恢复（推荐）」 when asked to authorize recovery and recheck under that separate-identity boundary.
- Criteria A-001 and A-003 describe that boundary. After the fresh independent check passed, the user was shown a four-item summary corresponding to A-001 through A-004 (init/shared and separate identities; learn data root; read-only doctor and safe pointer resolution; unresolvable-root guidance), and selected 「确认四项（推荐）」 to confirm those four requirements and authorize self-acceptance. This records confirmation of the summarized requirements, not review of every sentence or acceptance of unchecked results.
- Pointer removal and migration of real user data remain out of scope. No release is included.

## Open verification

- Independent checking of corrected A-001 through A-004 and cross-feature impact is in progress. Acceptance requires fresh recorded evidence and all applicable gates.
