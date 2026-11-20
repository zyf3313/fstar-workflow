# fstar prompt states

Per-prompt breadcrumbs selected by current task state (Trellis
workflow-state style). The prompt-context hook injects exactly one block per
user prompt; when this file or the needed tag is missing, the hook degrades
to a single fixed line instead of staying silent.

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
and document flow, then an executable plan is formed after the user reviews
the documents. The clarify design-tree frontier must be empty before the
plan is written: an unanswered frontier question is an unresolved
requirement, not optional context.
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
