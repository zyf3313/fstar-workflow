---
name: fstar-plan
description: "Create an executable plan after review, without another gate. 评审后自动形成执行计划。"
---

# Plan

## Do NOT use when
- Requirements are still ambiguous or any frontier question is open: use `fstar-clarify` until the frontier is empty.
- The task is still in `planning` and its documents have not been user-reviewed yet: the plan runs only after the user reviews the planning documents; replan after requirements change is a `fstar-continue` action (and requires an in-progress task).
- The goal is execution, not planning: use `fstar-execute`.

Run automatically after the user reviews planning documents; do not request a second plan approval. Read current valid documents, research, applicable full specifications, and relevant code/tests. Maintain plan.md yourself using the task plan template with Summary, Patterns to Mirror, Files to Change, Tasks, Validation, Risks, Acceptance. Give each item an ID, source fingerprint, priority, dependencies, parallel conditions, completion criteria, and test/document responsibility. Return scope, solution, or decomposition uncertainty to clarify.
