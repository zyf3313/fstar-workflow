---
name: fstar-archive
description: "Archive an accepted tree, then show factual stale candidates. 归档验收任务并展示长期候选。"
---

# Archive

## Do NOT use when
- The task is not accepted yet: complete `fstar-check` and user acceptance first.
- The user wants to resume or rework the task: use `fstar-continue` (replan/reopen).
- You would archive a different task than the confirmed one automatically: reminders never auto-archive.

Use `fstar archive <task> --workflow` with explicit user confirmation, requested and received in natural language — never as a command for the user to run. The command checks the current task's persistent-task `archive` grant before starting an archive. Verify user acceptance, fresh independent check evidence, delivery baseline, child tree, leases, blockers, and correctness questions through core APIs.

For learning, review the conversation actually available to this session, recorded user corrections, and accessible task materials for durable candidates. Record which sources were reviewed and which were unavailable; never imply access to an entire chat history. Distinguish temporary task instructions from lasting knowledge, and propose project or user scope only with evidence of its applicability. Compare with existing candidates and knowledge to avoid duplicates. If the host exposes a dedicated fstar learning agent and background dispatch, hand off the source references and coverage to it and continue the main conversation without waiting. Report actual dispatch and eventual outcome; if the agent or background dispatch is unavailable or fails, report that and retain the candidate for a later opportunity rather than claim it was processed. A candidate never authorizes a write: use the existing learn proposal, grant, confirmation, and index checks. Do not interrupt an active correction to seek approval; present candidates when the work settles. Optional learning never blocks archive.

After core successfully archives the whole tree, and only then, show other long-unarchived candidates factually (with dates, technical thresholds, missing conditions, and defer/dedup facts) so the user can decide; the user decides in conversation, never by being told to run an archive command. Never archive another task automatically. Interrupted-archive recovery stays available through the same command and is not disabled by trimming; trimming the persistent-task `task`, `evidence`, `lease`, or `events` members never turns off archive recovery or event integrity.
