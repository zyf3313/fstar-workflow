---
name: fstar-plan
description: "Create an executable plan after review, without another gate. 评审后自动形成执行计划。"
---

# Plan

The restrictions below apply to creating or updating a plan. Storing a user-supplied planning document is a separate duty described below, including for simple tasks or before requirements review; it does not authorize planning actions.

## Do NOT use when
- Requirements for the next step are still ambiguous or a blocking decision is open: use `fstar-clarify` first. Non-blocking questions marked "可边做边确认" do not block planning.
- The task is still in `planning` and its basis has not been user-reviewed yet: the plan runs only after the user reviews the settled requirements; replan after requirements change is a `fstar-continue` action (and requires an in-progress task).
- The goal is execution, not planning: use `fstar-execute`.
- The item is simple: a plan is not required. A one-line goal plus its acceptance conditions (criteria.md) is enough to proceed to implementation; do not generate ceremony documents for trivial work.

Run automatically after the user reviews the settled requirements; do not request a second plan approval. Read current valid documents, research, applicable specifications, criteria, and relevant code/tests. Maintain plan.md yourself using the task plan template: an overall approach (goal and delivery, referencing clarify.md and criteria.md instead of repeating them), then steps each carrying the seven fields — purpose, inputs, actions, outputs, completion criteria, blocked-handling, dependencies-and-adjustment. Completion criteria cite criteria.md item numbers (e.g. "covers A-001"), not restated requirements. Give each step an ID for evidence and work-item references. Planned actions and verified facts stay strictly separated. Return scope, solution, or decomposition uncertainty to clarify.

## Storing user-supplied planning documents

For storage, require the planning-review grant member corresponding to the supplied document kind: `prd` for a PRD, `design` for a design, or `plan` for a plan. A `prd` or `design` grant permits this storage duty even if `plan` is excluded or unlisted; creating or updating a plan still requires `plan`. If the corresponding member is absent, negotiate it before storage. For session-only work without a task directory, keep the material in the conversation record passed to dispatch as routing specifies.

When the user supplies a planning document (this replaces drafting from scratch): preserve their content as the authority and map it onto the applicable task template structure (slots, item markers, artifact_map markers) without rewriting meaning; unknown facts stay 待确认, never filled by inference. Mark origin as user-supplied (author = the user, a provenance note naming the supplied document), never drafted-by-agent. The artifact_map marker registration (task.json meta.templates) still applies. The stored document must exist in the task directory before any implement dispatch.
