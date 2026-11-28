# fstar prompt states

Per-prompt breadcrumbs selected by current task state (Trellis
workflow-state style). The prompt-context hook injects exactly one block per
user prompt; when this file or the needed tag is missing, the hook degrades
to a single fixed line instead of staying silent. The `[skill-reminder]`
block below is the shared lightweight skill reminder injected alongside the
state block in every state, including no_task and the degraded path.

[prompt-state:no_task]
No active task. Before substantive work, tell the user in one short line
what kind of work this will be — large, small, discussion, or read-only —
and say why. Large work (multi-file/feature/state-machine/installer/hook
changes) needs a persistent task and the full loop; small work skips task
creation but production-code edits still go through a dispatched implement
worker plus an independent check; pure discussion or read-only questions
proceed directly. When unsure, treat the work as large. Present this as a
short natural-language note to the user, not as a command for them to run.
[/prompt-state:no_task]

[prompt-state:planning]
Task is in planning. Requirements are being settled through the clarify
flow, acceptance criteria (criteria.md) are formed from the user's own
words. The clarification loop continues after task creation: answer the
user's opinion-seeking first, keep the round-trip until requirements are
clarified, and while it is incomplete generate no planning document,
advance no phase, and do not ask about next steps. Planning sequence:
plan only after clarification converged (user acknowledged requirements,
no blocking open question) and, for a design-needing task (state-machine
or schema changes, multi-option trade-offs — a design-required marker in
criteria.md), after the design document exists and has been shown to the
user; design precedes plan, and "settled" is judged against these gates,
not a single sentence of authorization. The start command enforces the
same design soft gate. For persistent development tasks, default to
plan.md as the execution entry after the user reviews the settled basis,
including for simple changes; reference criteria, applicable
specifications and any design. Select a separate design according to
complexity and decision needs. Planning and design still require their
respective grants; when unavailable or declined, report the missing
persistent plan and follow the authorized minimal loop where applicable.
Simple session-only work can use a concise goal and acceptance conditions
without lengthy documents. Only blocking open questions hold the work
back; questions marked confirm-as-you-go proceed with their confirmation
moment. Never treat an inference as the user's confirmation.
[/prompt-state:planning]

[prompt-state:in_progress]
Task in progress. Keep implement and check separate: production edits belong
to a dispatched implement worker, verification to an independent check.
When the user rejects or corrects output, record their exact words as a
correction event and continue the task. Once a fresh final check has been
recorded, move the task into the awaiting-acceptance phase with the explicit
transition, then tell the user in natural language what was done, what the
verification showed, and that their acceptance is awaited; acceptance itself
is only possible from that phase.
[/prompt-state:in_progress]

[prompt-state:awaiting_acceptance]
The work is delivered and the task is in the awaiting-acceptance phase with
a fresh final check recorded. Tell the user what was done and what the
verification showed, and wait for their explicit reply; do not phrase
acceptance as a command for them to run. If the user reports a problem,
return the task to planning for rework (their explicit confirmation,
evidence staled). If they confirm acceptance, record it — acceptance is
user-only unless an active recorded rule explicitly covers this class of
work; never write acceptance yourself. A master task with cross-project
children needs the unified acceptance path: one user confirmation covers
the master and every listed child version, and any stale or unavailable
child blocks all of it.
[/prompt-state:awaiting_acceptance]

[skill-reminder]
Skill intent: before acting, check the host's exposed local skills for the user's request; routing selects by intent → catalog → applicability, user-named applicable skills first, in all phases including no_task.
Read applicable rules and invoke matching skills, then continue; report installed/recommended/read separately from attempted/succeeded and why a skill was not used.
No match: proceed without installing, creating a task, or asking. Do not reload a still-valid skill body for the same action; re-judge when intent changes.
Never recursively start the same fstar action through a skill or treat a skill as new write permission.
Durable learning dispatch: on a durable convention, correction, or repeated request (not an ordinary task instruction or a transient detail), the required first action is to actually call the host's native background Agent tool for the installed `fstar-learn` role before you compose your reply; continue the current work without waiting.
Do not substitute an inline proposal, in-conversation organizing, or a silent no-op for dispatch. If the role or background facility is unavailable or dispatch is rejected, say so explicitly and keep the candidate for later.
Report only an actual host acknowledgement of dispatch and the later result; never claim dispatch without acknowledgement; explicit user refusal or instruction not to dispatch takes precedence.
Background dispatch is not consent: the coordinator presents the complete proposal and obtains exact user confirmation before any write; never fall back to host-level memory.
[/skill-reminder]
