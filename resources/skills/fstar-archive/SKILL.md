---
name: fstar-archive
description: "Archive an accepted tree, then show factual stale candidates. 归档验收任务并展示长期候选。"
---

# Archive

## Do NOT use when
- The task is not accepted yet: complete `fstar-check` and user acceptance first.
- The user wants to resume or rework the task: use `fstar-continue` (replan/reopen).
- You would archive a different task than the confirmed one automatically: reminders never auto-archive.

Use `fstar archive <task> --workflow` with explicit user confirmation. The command checks the current task's persistent-task `archive` grant before starting an archive. Verify user acceptance, fresh independent check evidence, delivery baseline, child tree, leases, blockers, and correctness questions through core APIs. Offer authorized learn work without making optional candidates block archive. After core successfully archives the whole tree, and only then, show other long-unarchived candidates with dates, technical thresholds, missing conditions, and defer/dedup facts. Never archive another task automatically. Interrupted-archive recovery stays available through the same command and is not disabled by trimming; trimming the persistent-task `task`, `evidence`, `lease`, or `events` members never turns off archive recovery or event integrity.
