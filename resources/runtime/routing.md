# fstar routing

This is the sole package routing source. It decides what to invoke before invocation; commands remain responsible for state validation.

## Local skill selection (all phases and no_task)

Before acting on any request, main and sub agents alike select applicable
local skills from the host's exposed skill catalog (the skills the host
itself lists; fstar never scans skill directories itself and never installs
a skill to make one applicable). The selection order is: understand the
current intent and its action scope → look through the host-exposed skill
catalog → judge applicability (a skill that does not cover the goal is not
selected) → actually invoke the matching skill's applicable rules and then
continue the request. The task phase is only context: the same intent
selects the same applicable skill in planning, in_progress,
awaiting_acceptance, or with no task at all.

- A skill the user explicitly names comes first when it is available and
  applicable; when it is not available or not applicable, say so explicitly
  instead of silently substituting another.
- No match is a normal outcome: proceed with the request, do not install
  skills, do not create a task because of skill selection, and do not ask
  the user about it.
- Several plausible candidates: choose the reasonable minimal set that
  covers the goal; ordinary ambiguity takes the default and does not block.
  Only goals, scope, permissions, or irreversible decisions ask the user.
- Do not re-load a skill body that is still valid for the same action;
  re-judge the selection when the intent changes.
- Invoking a skill never widens write permission, and a skill must never
  recursively start the same fstar action (no fstar skill that performs an
  fstar workflow action dispatches another fstar worker for that same
  action).
- Report honestly: installed, recommended, read, attempted, and succeeded
  are separate states; a skill that was never invoked must say why.

When dispatching a worker, pass the selection as the payload's
`selected_skills` (skill id, source entry, reason, applicable sub-task
scope) when applicable; the worker may supplement from its own exposed
capabilities and returns actual usage in `skill_usage` (attempted /
succeeded / failed / not_used with the reason). Selection never counts as
execution. Old dispatches without skill fields stay valid.

## Hard rules

Four constraints are always binding, everywhere in the workflow:

1. **Never treat an inference as the user's confirmation.** A recommendation, an assumed habit, or a probable preference may shape proposals and low-impact defaults, but enlarging permissions, forming lasting conventions, or recording acceptance needs the user's explicit words.
2. **Never treat a plan as completed.** Only actually executed and verified work counts as done; a written plan, an expectation, or an in-progress attempt never does.
3. **Never act beyond the authorized scope without asking.** When work would expand past what the user asked for, pause and confirm the expansion first.
4. **After requirements or outcomes change, re-evaluate the affected acceptance conclusions.** A conclusion that predates the change it invalidates is not fresh; re-check before relying on it. Re-verification is scoped by the affected criteria items and their dependencies: re-check the criteria items the change touches plus every item that depends on them, not the whole task; when the affected scope cannot be determined, fall back to full re-verification (conservative). The final overall check must still be fresh: after any re-verified change, a new final read-only check is required before acceptance again.

Implement/check separation stays a hard safety baseline: production edits belong to a dispatched implement worker, verification to an independent check — a scenario's own rules may also require independent checks (complex verification, independent judgment, parallel needs). Acceptance stays user-only (one authorized rule-based exemption exists, below). Generate criteria.md for any formal delivery. For a persistent development task, default to plan.md as the execution entry even when the change is simple: reference criteria, applicable specifications and any design, and keep its detail proportional to the work. Choose a separate design by complexity and decision needs; when used, it records the solution and key decisions. Clarification and other documents depend on uncertainty and hand-off needs. Simple session-only work can proceed on a concise goal and acceptance conditions without a lengthy plan or design.

Creating or updating plan.md requires the planning-review `plan` grant; a separate design uses the applicable `design` grant. The default does not grant either member. If unavailable or declined, explain that the persistent plan cannot be created under the current grant and continue the authorized minimal session loop where applicable; do not silently claim a plan exists or repeatedly seek a refused grant.

## Always-available minimal loop

Clarify the goal in conversation, invoke `fstar-execute` through the host native implement role, invoke independent `fstar-check`, return every failed check to repair and recheck, then wait for explicit user confirmation. Session nodes are not persisted and no fstar metadata is created. This does not prohibit delivery files. Never fall back to main-Agent production editing. `fstar-debug` is core-automatic: route to it when a native dispatch fails twice (at most one automatic retry, with the prior reason) or a repair shows no progress.

## User-facing language

All fstar commands are agent-internal: the agent runs them itself and records what they produced. What the user sees is natural conversational language — what was done, what the verification showed, and what confirmation is awaited. Never reply to the user with a fstar command line or echo one back as the thing to do (never phrase confirmation as "run `fstar accept ... --confirm-user`"); the agent asks in plain words for an explicit yes/no or decision, and records the actual conversation as the confirmation source when one is required. This changes presentation only: confirmation stays explicit, one-time, user-initiated, and traceable in the event log.

## Extension negotiation

Package IDs are exactly `planning-review`, `persistent-task`, `multi-agent`, and `project-governance`. Grants are independent. Reuse an existing grant. Otherwise explain benefit and cost and recommend only one highest-value package. Default to full scope, allow explicit custom included/excluded capabilities, but never remove implement/check separation, repair after failure, or user-only completion. After refusal, continue the minimal loop and do not ask again unless new facts materially change value or cost. Planning authorization does not create task.json. Mid-work authorization imports valid work without redoing it. A user-supplied planning document must be stored into the current task directory before any implement dispatch, adapted to the applicable template structure with origin noted — which requires the planning-review grant covering the corresponding member, so negotiate that grant first when absent; a user handing over planning material is a new fact that materially changes value. Never dispatch implement while user-supplied planning material is still unstored; for session-only work without a task directory, the material stays in the conversation record passed to dispatch.

The session context always lists the four optional packages and injects the project and user indexes read-only. Discovery and reading never imply authorization. When the user states a durable convention or asks to record something, treat it as a learn candidate. If no grant covers the destination (`rules` or `memory` under `project-governance`), offer that package before writing anywhere. Never silently fall back to a host-level memory; if the user declines the fstar path, say so explicitly.

Before consuming a package member, check that member is in the current grant's `included` list; `excluded` and unlisted members are unavailable. Task recovery reads the task's `extensions` records; never substitute `capabilities`, which is a separate schema field and never authorizes workflow behavior. For session-only work, retain the authorization records returned by `extension enable` in the caller's session and pass them as the `extensions` array in hook and dispatch JSON payloads. On disable remove that record from subsequent payloads. Separate CLI invocations cannot remember these grants. These records guide cooperating callers and are not a same-permission security boundary.

- Planning/review need: use `fstar-clarify` only with `clarify`. Creating or updating a plan through `fstar-plan` requires `plan`; storing a user-supplied planning document through `fstar-plan` instead requires the included member covering that document kind (e.g. `prd`, `design`, or `plan`), and does not require `plan` for a `prd` or `design` document. Use the editor and document check only when their respective members are included. Clarify hands off to plan or execution when nothing blocking is left open: questions marked "可边做边确认" (confirm-as-you-go) do not block the hand-off; an unanswered blocking question is an unresolved requirement, not optional context.
- Persistence/recovery need: `fstar-continue` requires `recovery` (pass `--workflow`), `fstar-archive` requires `archive` (pass `--workflow`), and `fstar dispatch orphan <task> --workflow` requires `recovery`. These workflow consumption entries reread the stored grant at call time.
- Safety machinery always on: the `task`, `evidence`, `lease`, and `events` members never gate task consistency or recoverability. Evidence staleness and invalidation, lease acquisition/renewal/expiry/takeover, whole-tree archive recovery, and append-only event integrity keep running for any persistent task regardless of how those members are trimmed; harvesting a worker result, invalidating evidence, or recovering an interrupted archive never checks an extension member. Custom trimming of `task`/`evidence`/`lease`/`events` only records the user's intent to skip optional persistent-lifecycle workflow consumption; it can never disable safety bookkeeping.
- Enhanced collaboration: require `research`, `parallel-implement`, `version-injection`, or `change-propagation` for the respective enhancement; base implement/check remains available.
- Governance: use specs, knowledge, rules, or memory only with the corresponding included member; route learning according to its actual destination. Project initialization and its user-root creation are exempt from the learn-approval requirement: `fstar init` may create the skeleton and auto-create or repair the user root before any governance grant exists, but later writes to specs, knowledge, rules, or memory still require the included member, the learn proposal, its hash, and the user's exact confirming quote.

A recall intent queries indexed knowledge and archived task listing with sources and applicability differences; it does not restore an archived task and has no recall skill. Continue resumes only the current task and never scans archive candidates. Only after a successful `fstar-archive` operation may routing show other long-unarchived candidates; reminders never auto-archive. `fstar-help` explains observed installed entries only.

## Shared global resources

Workflow resources (skills, agent cards, hooks) are installed and updated globally by default: one global update serves every project, and a project keeps only its own tasks, specs, and identity. A project that still carries its own resource copies or a resource pin gets one natural-language migration note at session start: the comparison itself is read-only and writes nothing at all (not to the project, not to the tasks, not to the runtime). Showing the question is a separate explicit operation — run `fstar resource-remind --session ID` first; it decides and records whether the question may be shown in this session, so the same question is not asked twice in one session (a clear/compact keeps the same session). Only a path that got the "may show" result asks the question, and a record that cannot be written is reported, never claimed. The offer is not an authorization: only the user's explicit yes moves anything (the migration command takes a confirmation file that carries the user's approval), and only copies the installer provably owns and that were not modified are moved (the rest are kept and reported). Record the user's decision yourself: a yes is the confirmation source for the migration; a deferral (`fstar resource-defer`) is remembered for that project and target version so the same question is not asked again, while a new global version makes the project eligible again. Never claim a migration happened because an offer was shown. Resource migration and data-schema migration are separate: schema work always goes through the schema migration command, never as a side effect of a resource update. If the global entry is incomplete or modified, report that diagnosis instead of offering the migration. A running session may still hold the previous resource version: say that a restart (or clear/compact) is needed for the new version to apply.

When the coordinator identifies a potentially durable correction, repeated request, or convention in the conversation, it must actually dispatch the installed `fstar-learn` role through the host's native background agent facility as its first action — call the host Agent tool before composing the reply — and then continue the current work without waiting. Never substitute an inline proposal or in-conversation organizing for that dispatch, and never silently skip it. Pass only accessible relevant conversation excerpts, source references and coverage, the current task or session-only context, and applicable grants; do not claim the worker can see the full chat. Avoid duplicate concurrent dispatches for the same candidate and source; incorporate later corrections before proposing a write. The role can identify and organize candidates without a governance grant; preparing a bridge proposal requires the relevant grant, and applying it also requires exact user confirmation. The coordinator presents a complete proposal when the work settles and handles real user approval; background dispatch does not imply consent. Record or report only an actual host acknowledgement and later result; never claim a dispatch without one. If the role or background capability is unavailable, dispatch is rejected, or the worker fails, report the actual condition explicitly and preserve the candidate in the current conversation for later; do not block the main task, fabricate success, run it synchronously, or bypass a refusal. Explicit user instructions not to dispatch take precedence. This is semantic recognition by the coordinator, not a guaranteed scan of every turn, and it must not fire for ordinary task instructions or transient details.

Two learning-loop rules apply before proposing anything. First, rejected proposals: before proposing an approach, check the project's rejected ledger (`.fstar/knowledge/references/rejected.md`, one index line injected at session start; read the file when the line is present) and the user's rules for previously denied approaches — a hit means do not re-propose it; cite the user's recorded words when asked why. Recording a rejection follows the normal `fstar-learn` authorization pipeline (project-governance `knowledge` member, proposal, hash, and the user's exact quote); it is never recorded silently. Second, corrections: when the user explicitly rejects or corrects produced output mid-task, the coordinator records one `fstar correction record` event carrying the user's exact words as `user_signal` (pure capture, no knowledge write, no behavior change, no grant required) and then continues the task; background preparation may start immediately, but do not interrupt the flow to offer a learn candidate until the work settles.

Recalled experience follows the learn read protocol before it is used: memories are read through the `fstar-learn` bridge's read action with the current item's scope tags, so scope, expiry and applicability filtering actually run before a habit is applied — an `inferred` confidence is a guess, never a rule, and a memory with prose conditions stays `unknown` until the user explicitly judges it. Reading never writes and never creates new memories; correcting or retiring a memory goes through the same authorized proposal pipeline as any write, keeping the old record auditable.

Acceptance stays user-only, with one authorized exemption path: a user-recorded rule may delegate acceptance for a class of work (for example development tasks — new features, extensions, fixes). When an active/enforced rule in the user's rules or project specs explicitly covers the task's class of work, the coordinator follows the full self-acceptance closing procedure defined in `fstar-execute` — its applicability gates (every criterion judged machine-verifiable with evidence, no user-judgment item), the gate check, the self-acceptance report, and its never-covered list — and records acceptance citing that rule (`accepted_via_rule`). A fresh final check alone is never sufficient: the exemption exists only inside that procedure. No rule match, no exemption — priority or risk level alone never waives acceptance; and every exemption traces to the user's recorded words. When presenting a completed delivery or an acceptance request, describe in natural language what was done, what the verification showed, and that the user's acceptance is awaited — the fstar commands that record the outcome are agent-internal and never appear as the reply.
