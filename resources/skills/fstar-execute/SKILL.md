---
name: fstar-execute
description: "Coordinate native implement, independent check, and user confirmation. 协调原生实施、独立检查与用户确认。"
---

# Execute

## Do NOT use when
- Resuming after an interruption, lease takeover, or session restart: use `fstar-continue` first.
- A dispatch has failed twice or repair shows no progress: `fstar-debug` is core-automatic.
- Requirements are unsettled or the plan predates a replan: back to `fstar-clarify`/`fstar-plan` first.

You are the main conversational Agent: keep the dialogue with the user, coordinate, and dispatch the rest to background workers (C-11) — document editing, sustained research, implementation, and checking go to background sub-agents; a very short lookup may be answered directly. Verify current authorization, baseline, and either a valid plan or the session goal before dispatching. If the user supplied planning material that is not yet stored in the task directory, stop before dispatching implement and route it through fstar-plan storage first.

Before acting, select applicable local skills following routing's local-skill rules (semantic intent → the host's exposed skill catalog → applicability → actual invocation; user-named applicable skills first; the phase is only context). When a selection applies to the dispatched sub-task, pass it in the payload's `selected_skills` (skill id, source entry point, reason, and the sub-task scope it covers); the worker may supplement and returns actual usage in `skill_usage`. Selection never counts as execution, a skill never widens a grant or allowed_paths, and a skill must not recursively start the same fstar action.

Every dispatch carries explicit version and evidence basis, scope, and completion conditions: dispatch_id, task_ref, role, plan_item_ids, baseline, input versions/fingerprints, allowed_paths, read_context, required validation, and completion/block/failure conditions. When a worker returns, first verify the result is still timely — an older result never overwrites a newer decision; if inputs changed meanwhile, re-dispatch instead of harvesting stale work. Record handoff profiles in subagents.md (single dispatch) or the subagents/ directory (repeated/parallel dispatches): one entry per dispatch with versions, basis, scope, completion conditions, returned result, and whether a newer decision superseded it.

Use the host native Agent mechanism to dispatch fstar-implement; never fall back to the main Agent writing production code. Coordinate dependency order, allowed paths, and shared resources; the coordinator alone updates plan progress or task state (task.json: status, work_items, next_step). Stop implement writes for handed-off scope, propagate conversation/file changes, then dispatch an independent fstar-check. Failed checks return to repair; only the user confirms completion.

After a fresh final check is recorded, move the task into the awaiting-acceptance phase with the explicit transition (`fstar accept <task> --awaiting`); the harvest never changes the phase by itself, and completion is only possible from that phase. A master task with cross-project child links uses the unified acceptance path (`fstar accept <task> --unified`): one user confirmation covers the master and every listed child version, and a stale, unavailable, or not-yet-awaiting child blocks the whole acceptance with its reason.

When the task enters awaiting-acceptance (and again when you request the unified confirmation), tell the user in natural language what was done, what the verification showed — including each listed child version in a unified acceptance — and that their explicit acceptance is awaited. These fstar commands are agent-internal: run them yourself and record their outcome; never present a command line to the user as the way to confirm. When the user confirms in conversation, record the acceptance with their confirmation as the source (the conversation quote and reference for conversation sources).

## Multi-file document-edit coordination

Own the specified deliverable files wherever the user's delivery preference puts them — there is no fixed doc/ location; the default is to follow the preference recorded at clarification close. Queue edits to the same file: every write must use a background fstar-editor dispatch carrying the discussion revision, source references, baseline fingerprint, and the exact files/items; do not dispatch two edits against the same baseline concurrently. Keep the main conversation available. Before acceptance, collect results, reject a stale-baseline overwrite (the editor dispatch must re-read the current baseline), reread slots/IDs/references, then request an independent consistency check using document-checklist.md. Syncing an already approved, unchanged scope does not require another approval; editing never proves approval. Maintain the deliverables registry: register new, moved, or versioned deliverables in the task's `deliverables` entries in task.json so the acceptance flow can trace them.

One acceptance delegation exists: an active/enforced user rule that explicitly covers this class of work (e.g. development tasks: new features, extensions, fixes) lets the agent complete acceptance via the self-acceptance closing procedure below instead of waiting for the user. No matching rule, no delegation; priority or risk level alone never waives acceptance.

Self-acceptance closing procedure (follow it literally, in order):

1. Applicability: the task category is covered by an active/enforced user rule, and the task was completed after that rule took effect. Otherwise treat it as a normal awaiting-acceptance.
2. Judge criteria.md item by item: for every A-xxx item give a verdict (satisfied / not satisfied / unverified) with an evidence link (test output, check-report section, or source-verification record). If any item's 判定方式 is `user-judgment`, stop the self-acceptance immediately — move the task to waiting_user and ask the user to judge that item.
3. Gate check, all five required: criteria come from user-confirmed requirements; every criterion is `machine`; the independent check and the final read-only check both passed with a checker distinct from every deliverer instance; evidence is fresh (no delivery file changed after the final check); no failed/blocked/unverified item and no unresolved blocker. Any gate failing → stop, task to waiting_user.
4. Write the report to `checks/self-acceptance.md` in the task directory: the per-item verdict table, the five-gate check record, and the cited evidence.
5. Record the acceptance with `fstar accept <task> --rule RULE.json --confirmation SOURCE.json`. The rule file carries `rule_ref` (the rule file path), `quote` (the user's authorization words), `criteria_refs` (the judged A-xxx item ids), `report` (the report path), and `scope` (what the rule covers); the event data carries `accepted_via_rule` with these fields for later audit. The CLI also requires a confirmation source file: build it from the user's original rule authorization (a traceable source such as the recorded conversation or the rule's user-confirmed quote), bound to the current task snapshot — never fabricate a new on-the-spot user confirmation. Prerequisites before recording: a fresh final check and the `--awaiting` transition (`fstar accept <task> --awaiting`) have already been done. Older rule files without the new fields remain valid (the fields are optional).
6. At the next turn, proactively tell the user the self-acceptance verdict and where the report is. These fstar commands are agent-internal: run them yourself and record their outcome; never present a command line to the user as the way to confirm.

Never-covered list — self-acceptance never applies to these, the user must verify them personally: version releases and npm publish; git push to a remote and branch merges; data deletion, destructive changes, schema migrations; anything published externally (articles, announcements, public-repo Issue/PR replies); modifying the acceptance mechanism itself (accept semantics, evidence validation, routing hard rules); anything involving secrets, accounts, or payments.

Anti-drift: the rule text may only change through a fresh explicit user authorization (learn flow); a modified rule invalidates old citations immediately. The user may spot-check any self-acceptance report; when the user challenges a report, that acceptance conclusion returns to awaiting-acceptance. When the user is present during a task and asks to verify it personally, that task loses self-acceptance eligibility.

When the user explicitly rejects or corrects produced output mid-task, record one `fstar correction record` event with their exact words as `user_signal` (pure capture — no knowledge write, no behavior change), then continue the task.
