---
name: fstar-execute
description: "Coordinate native implement, independent check, and user confirmation. 协调原生实施、独立检查与用户确认。"
---

# Execute

## Do NOT use when
- Resuming after an interruption, lease takeover, or session restart: use `fstar-continue` first.
- A dispatch has failed twice or repair shows no progress: `fstar-debug` is core-automatic.
- Requirements are unsettled or the plan predates a replan: back to `fstar-clarify`/`fstar-plan` first.

Verify current authorization, baseline, and either a valid plan or the session goal. If the user supplied planning material (PRD/design/clarify content) that is not yet stored in the task directory, stop before dispatching implement and route through fstar-doc storage first. Use the host native Agent mechanism to dispatch fstar-implement; never fall back to the main Agent writing production code. Carry per-input version and fingerprint data (`input_versions`/`read_context` path + sha256, or the injected `{path, sha256, version}` envelope) on every dispatch so harvest can verify inputs byte-for-byte; enhanced version injection beyond that baseline requires the multi-agent `version-injection` member. Coordinate dependency order, allowed paths, and shared resources; the coordinator alone updates plan progress or task state. Stop implement writes for handed-off scope, propagate conversation/file changes, then dispatch an independent fstar-check. Failed checks return to repair; only the user confirms completion.

After a fresh final check is recorded, move the task into the awaiting-acceptance phase with the explicit transition (`fstar accept <task> --awaiting`); the harvest never changes the phase by itself, and completion is only possible from that phase. A master task with cross-project child links uses the unified acceptance path (`fstar accept <task> --unified`): one user confirmation covers the master and every listed child version, and a stale, unavailable, or not-yet-awaiting child blocks the whole acceptance with its reason.

When the task enters awaiting-acceptance (and again when you request the unified confirmation), tell the user in natural language what was done, what the verification showed — including each listed child version in a unified acceptance — and that their explicit acceptance is awaited. These fstar commands are agent-internal: run them yourself and record their outcome; never present a command line to the user as the way to confirm. When the user confirms in conversation, record the acceptance with their confirmation as the source (the conversation quote and reference for conversation sources).

One acceptance exemption exists: when the final check is fresh and an active user rule explicitly delegates acceptance for this class of work (e.g. "docs-only changes with a green final check"), acceptance may be recorded via `fstar accept` citing that rule (event data carries `accepted_via_rule` with the rule's source and quote) and the citation must be surfaced to the user at the next turn. No matching rule, no exemption; priority or risk level alone never waives acceptance.

When the user explicitly rejects or corrects produced output mid-task, record one `fstar correction record` event with their exact words as `user_signal` (pure capture — no knowledge write, no behavior change), then continue the task.
