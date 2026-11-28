---
name: fstar-plan
description: "Create an executable plan after review, without another gate. 评审后自动形成执行计划。"
---

# Plan

The restrictions below apply to creating or updating a plan. Storing a user-supplied planning document is a separate duty described below, including for simple tasks or before requirements review; it does not authorize planning actions.

## Trigger conditions (planning sequence)

Plan only after both explicit gates hold, never after a single-sentence authorization: (1) clarification has converged — the user has acknowledged the requirements and no blocking open question remains; (2) for a task that needs a design record (state-machine or schema changes, multi-option trade-offs, cross-cutting mechanisms), design.md already exists and has been shown to the user. Design precedes plan: the plan decomposes dispatch steps from the design; planning the design work as an early plan step is not allowed as a fallback. A task whose criteria.md declares a design need (the `design-required` marker) without a design.md is not plan-ready. Simple tasks with no design need are unaffected.

## Do NOT use when
- Requirements for the next step are still ambiguous or a blocking decision is open: use `fstar-clarify` first. Non-blocking questions marked "可边做边确认" do not block planning.
- Clarification has not converged or the design (when required) is missing or unreviewed: return to `fstar-clarify` / design drafting.
- The task is still in `planning` and its basis has not been user-reviewed yet: the plan runs only after the user reviews the settled requirements; replan after requirements change is a `fstar-continue` action (and requires an in-progress task).
- The goal is execution, not planning: use `fstar-execute`.
- The work is simple and session-only: a concise goal and acceptance conditions can suffice without a lengthy plan or design. This exception does not omit the default plan for a persistent development task.

For persistent development tasks, use plan.md as the default execution entry, including simple changes, with detail proportional to the task. Creating or updating it requires the planning-review `plan` member; the default is not a grant. If that member is unavailable or declined, report that no persistent plan was created and follow the authorized minimal loop where applicable without re-asking after a refusal. Choose a separate design according to complexity and the need to record a solution and key decisions; its creation or storage requires the applicable `design` member.

Run automatically after the user reviews the settled requirements; do not request a second plan approval. Read current valid documents, research, applicable specifications, criteria, and relevant code/tests. Have the plan.md written through a dispatched worker (fstar-implement for planning within an authorized dispatch, fstar-steward for first-draft document creation, or fstar-editor for later entries) — the main conversational Agent stays on dialogue, decisions, and dispatch (A-008); when the host provides no sub-agent facility, the main Agent may write it directly for that case. The plan uses the task plan template: an overall approach (goal and delivery, referencing criteria.md, applicable specifications, and any clarify.md or design document instead of repeating them), then steps each carrying the eight fields — purpose, inputs, actions, outputs, completion criteria, verification method, blocked-handling, dependencies-and-adjustment. Every step binds an independent objective verification method ("how is this proven done": a test command, an independent check, a source verification); a step whose acceptance cannot be objectively verified is a vague step — return it to clarification instead of dispatching it. Completion criteria cite criteria.md item numbers (e.g. "covers A-001"), not restated requirements. Give each step an ID for evidence and work-item references. Planned actions and verified facts stay strictly separated. Return scope, solution, or decomposition uncertainty to clarify.

## Storing user-supplied planning documents

For storage, require the planning-review grant member corresponding to the supplied document kind: `prd` for a PRD, `design` for a design, or `plan` for a plan. A `prd` or `design` grant permits this storage duty even if `plan` is excluded or unlisted; creating or updating a plan still requires `plan`. If the corresponding member is absent, negotiate it before storage. For session-only work without a task directory, keep the material in the conversation record passed to dispatch as routing specifies.

When the user supplies a planning document (this replaces drafting from scratch): preserve their content as the authority and map it onto the applicable task template structure (slots, item markers, artifact_map markers) without rewriting meaning; unknown facts stay 待确认, never filled by inference. Mark origin as user-supplied (author = the user, a provenance note naming the supplied document), never drafted-by-agent. The artifact_map marker registration (task.json meta.templates) still applies. The stored document must exist in the task directory before any implement dispatch.
