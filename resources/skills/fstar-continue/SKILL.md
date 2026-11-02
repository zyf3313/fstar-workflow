---
name: fstar-continue
description: "Resume the current authorized task from verified state. 核实状态后恢复当前任务。"
---

# Continue

Use `fstar continue <task> --workflow` for recovery and pass `--workflow` on each continue action. The command checks the current task's persistent-task `recovery` grant; the caller must not substitute session records for stored grants. Read and verify the current task version, artifacts, worker facts, lease, and existing extension grants before choosing the next authorized action. Do not promise worker-context recovery. For an orphan, `fstar dispatch orphan <task> --workflow` provides a read-only report; present takeover, redispatch, or abandon choices to the user. Resume current work only; do not search history or issue archive reminders. Trimming the persistent-task `task`, `evidence`, `lease`, or `events` members never disables evidence staleness, lease safety, or recovery bookkeeping; it only records intent to skip optional persistent-lifecycle consumption.
