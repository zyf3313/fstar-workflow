# Plan — prompt-context-hook

## P-001 Fifth hook semantic prompt-context (R-001)

Scope: new UserPromptSubmit hook that injects a short per-prompt state-selected
breadcrumb reminding the agent to make a workflow-size decision before acting.

Items:

- P-001.a resources/runtime/prompt-states.md — four [prompt-state:X] blocks
  (no_task / planning / in_progress / awaiting_acceptance) with the workflow
  decision rules for no_task; planning/in_progress/awaiting_acceptance blocks
  carry the respective routing reminders.
- P-001.b src/fstar/runtime/hooks.py — HOOK_NAMES adds "prompt-context";
  prompt_context() derives state from the session's current task (no task →
  no_task; planning → planning; in_progress + awaiting_acceptance →
  awaiting_acceptance else in_progress; dropped → no_task; completed →
  awaiting_acceptance), parses prompt-states.md via the effective resource
  root, emits one block inside <prompt-state>; degraded single line when the
  resource or tag is missing (never silent); outside an initialized project
  emits nothing. CLI subparser, _HANDLERS entry, run_hook dispatch,
  HOST_EVENT_MAP entries for both hosts.
- P-001.c src/fstar/runtime/registration.py — HOOK_SEMANTICS adds the fifth
  semantic; CLAUDE_PLAN UserPromptSubmit entry (verified True, timeout 15,
  empty matchers, owned_by fstar); CODEX_PLAN UserPromptSubmit entry
  (schema_event userPromptSubmit, verified False with to_verify note, manual
  fallback).
- P-001.d src/fstar/installer.py — HOOK_SEMANTICS tuple and EXPECTED_COUNTS
  hooks: 5.
- P-001.e tests — hook behavior (no-task decision rules, planning/in_progress
  states, awaiting_acceptance for completed, degraded line via missing
  resource root, session isolation, read-only), registration plan entries on
  both hosts, installer/doctor/wiring/e2e hook counts updated to 5,
  content test for prompt-states tags and decision keywords.
- P-001.f node scripts/build-package.cjs regenerates the manifest including
  the new resource; full Python suite and node package tests green.

Constraints honored: existing four semantics untouched (only additive entries
and count updates); no write operations added anywhere; routing.md unchanged.

Out of scope: PreToolUse interception; live codex UserPromptSubmit verification
(carries to_verify note); promoting the user resource cache.
