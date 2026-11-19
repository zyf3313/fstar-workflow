# fstar prompt states

Per-prompt breadcrumbs selected by current task state (Trellis
workflow-state style). The prompt-context hook injects exactly one block per
user prompt; when this file or the needed tag is missing, the hook degrades
to a single fixed line instead of staying silent.

[prompt-state:no_task]
No active task. Before substantive work, output a one-line workflow decision:
large | small | discussion | read-only. large (multi-file/feature/state-machine/
installer/hook changes) must create or reuse a persistent task and run the full
loop; small skips task creation but production-code edits still go through
dispatched implement + independent check; pure discussion/read-only proceeds
directly. When unsure, treat as large.
[/prompt-state:no_task]

[prompt-state:planning]
Task is in planning. Use fstar-clarify / fstar-doc / fstar-plan per grant;
each requires its planning-review member. The clarify design-tree frontier
must be empty before any plan handoff: an unanswered frontier question is an
unresolved requirement, not optional context.
[/prompt-state:planning]

[prompt-state:in_progress]
Task in progress. Keep implement/check separation: production edits belong to
a dispatched implement worker, verification to an independent check. Follow
the dispatch protocol (identity, baseline, scope); record corrections as
fstar correction record events when the user rejects or corrects output.
[/prompt-state:in_progress]

[prompt-state:awaiting_acceptance]
Implementation is done and awaiting acceptance. Run a fresh final check over
the delivered state, repair in scope and recheck on failure. Acceptance is
user-only unless an active recorded rule explicitly covers this class of
work; never write acceptance yourself.
[/prompt-state:awaiting_acceptance]
