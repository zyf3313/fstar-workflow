---
name: fstar-continue
description: "Resume the current authorized task from verified state. 核实状态后恢复当前任务。"
---

# Continue

## Do NOT use when
- The task is actively running in this session: use `fstar-execute`.
- Requirements need rework: replan/reopen is a `fstar-continue` action, but the re-clarification itself belongs to `fstar-clarify`.
- The task is already accepted: use `fstar-archive`.

Use `fstar continue <task> --workflow` for recovery and pass `--workflow` on each continue action. The command checks the current task's persistent-task `recovery` grant; the caller must not substitute session records for stored grants. Read and verify the current task version, artifacts, worker facts, lease, and existing extension grants before choosing the next authorized action. Do not promise worker-context recovery. For an orphan, `fstar dispatch orphan <task> --workflow` provides a read-only report; present takeover, redispatch, or abandon choices to the user. Resume current work only; do not search history or issue archive reminders. Trimming the persistent-task `task`, `evidence`, `lease`, or `events` members never disables evidence staleness, lease safety, or recovery bookkeeping; it only records intent to skip optional persistent-lifecycle consumption.
