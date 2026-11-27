---
name: fstar-learn
description: "Save authorized knowledge with scope, conflict, and index checks. 按授权沉淀知识并核对归属。"
---

# Learn

## Do NOT use when

- The user has explicitly declined learning for the candidate: do not dispatch, prepare, or write it, and do not ask again without materially new facts.
- The request is only to resume the current task, not to discover or organize durable knowledge: follow the applicable continuation workflow instead.

## Entry and authorization

The coordinator and a dispatched `fstar-learn` worker use different entry paths:

- **Coordinator:** When a durable candidate is identified, dispatch the dedicated role in the host's background facility as directed by routing and continue the main task; the dispatch is the required first action, and an inline proposal never substitutes for it. If it is unavailable or fails, report the limitation explicitly and retain the candidate for later. If the user is correcting task output, do not interrupt the correction to offer a candidate; present it when the work settles.
- **Dispatched worker:** Use this skill's read and preparation instructions for the assigned candidate. Do not dispatch another agent or ask the user questions; return candidates, missing authorization, and any complete proposal to the coordinator.

Discovery, read-only review, and organizing candidates need no project-governance grant. The bridge's `prepare` and `apply` actions require the grant covering the destination; without it the worker returns the candidate and missing authorization, and the coordinator may negotiate the grant subject to the user's decisions. Applying also requires the user's genuine approval of the exact proposal hash, scope and owners as specified below. Never invent or infer approval, bypass a refusal, or write without authorization.

Procedures ("how to do X step by step") are routed by applicable scope, not by their kind: a procedure whose applicability is this project goes under the project references category in the format below; a procedure the user explicitly states applies across projects goes to user rules (enforced or default convention) or user memory (preference or lesson) in the existing user knowledge format, with its user index updated; there is no separate `user/procedures` directory to invent. When the scope is unknown or cannot be shown to be cross-project, keep the candidate and report it undecided — do not write it anywhere and do not narrow it to project scope just because it is a procedure.

## Rejected-proposals ledger

When the user rejects a proposed approach and the rejection is durable (not a task-specific tradeoff), offer to record it in `.fstar/knowledge/references/rejected.md` with one entry per rejected approach:

```markdown
## <approach summary>
- rejected_at: YYYY-MM-DD
- user quote: "<the user's exact words>"
- reason: <why, from the user's words>
- scope: <this project | all projects — all-projects rejections belong in user rules instead>
```

Writing follows the normal pipeline (project-governance `knowledge` member, proposal, hash, user's exact quote). Cross-project rejections go to the user's rules, not this file.

## Procedure format

A procedure whose applicable scope is this project is recorded under `.fstar/knowledge/references/procedures/<name>.md` in the same authorized pipeline (`knowledge` member). A procedure the user explicitly states applies across projects is recorded under the user's `rules/<name>.md` or `memory/<name>.md` in the user knowledge format (rule strength or memory kind/trust, APPLIES/NOT, optional scope fields) with the user index updated — requiring the `rules` or `memory` member respectively, the same as any other user write. Each stage must carry an `evidence` field (how to prove the stage was done right); stages stay tool-agnostic (no host-specific commands, model names, or absolute paths). Workers read procedures live through dispatch `read_context` (path + sha256); the file in the knowledge base is the only authoritative copy. A procedure whose scope is unknown is not written: retain it as an undecided candidate.

Read complete indexes and applicable bodies, prefer an existing topic, and justify a new one. Show candidate content, source, destination scope, and conflicts; save only when that exact content and scope are authorized. Follow the coordinator or dispatched worker entry above; deferred optional learning does not block archive.

Invoke the packaged internal bridge with `python3 -I <package-root>/bin/fstar-bootstrap.py learn_bridge`, passing one JSON object on stdin. Resolve the package root from the installed fstar executable, not the current project. It returns one JSON envelope on stdout. This is an internal skill interface, not a new user command.

## Reading scoped experience (`action: "read"`)

Before relying on a recalled habit, read memory through the bridge's `read` action so scope, expiry and applicability filtering actually run. Supply absolute `project_root` and `user_root` plus a `selection` object: `topics`, `documents`, `dependencies`, `global_constraints`, `excluded`, `scope` (a list of the current reading's scope tags, e.g. `["scenario:payments", "item:task-42"]`), `applicability` (key → `{state: include|exclude|unknown, reason}`; a `conditions` memory needs an explicit user-backed judgement before it injects), and optional `snapshot_hash`; an optional `max_bytes` caps the budget. Every list must be a list; a bare string never silently iterates as scope tags or paths. Reads need no grant and write nothing.

The result carries the injected `documents` (with each memory's `confidence`, honestly reported — `inferred` is a guess, not a rule), every `excluded` entry with its reason (scope mismatch, `memory expired on <date>`, superseded, unknown conditions), `required_unloaded` deferred bodies, and the `snapshot_hash` a later assessment must carry. Do not treat `conflicts_pending: false` as "all applicability decided": read the `excluded` list itself — an unjudged `conditions` memory appears there with an `unknown` reason. Read results never imply write permission and never create new memories.

## Correction and retirement

User corrections and retirements go through the same `prepare`/`apply` pipeline as any write — there is no direct write path. A correction is one transactional group: `supersede` the old memory (its bytes and `source` stay on disk, auditably) and `create` the replacement carrying the new `source` (e.g. `user-correction-chat#7`) and an updated `confidence`. Example edits:

```json
[
  {"owner": "user", "path": "memory/deployment.md", "action": "supersede",
   "content": "<old document with status: superseded>"},
  {"owner": "user", "path": "memory/deployment-corrected.md", "action": "create",
   "content": "<replacement with the corrected body and the new source>"}
]
```

The proposal also updates the user index navigation (old entry removed, replacement added); do not claim an in-place overwrite preserves the original content — it does not. Retirement is the same shape without the replacement edit. Promotion of an inferred memory to a rule keeps its own explicit consent on both `prepare` and `apply`.

For `action: "prepare"`, supply absolute `project_root` and `user_root`, explicit `task_ref` (`session-only` or persistent task), `edits` (objects with `owner`, owner-relative `path`, `action`, and exact `content` or `rename_to`), `intent` (`summary`, `action`, `scope`, `source` with `source_type` and `reference`, and optional `topic`, `language`, `consent`, `extra_reference_files`), and `assessment` (reviewed source keys and byte digests, applicability, conflicts, coverage and language review). Session-only calls also carry the current `extensions` records; persistent calls omit them and read current grants from the task. If task commands use a custom `--runtime-root`, provide that exact absolute path as `runtime_root` on every persistent call; otherwise both use the default user runtime. The project must already be initialized. The provider validates paths, topic, indexes and reference closure; include explicit edits for affected references.

Present the returned complete `proposal` and `proposal_hash` for review, including all generated index changes. For `action: "apply"`, resend the exact inputs and add `confirmation` with `disposition: "approved"`, `source_type`, `source_ref`, the user's actual `quote`, `confirmed_at`, the returned `proposal_hash`, and exact `scope` and `owners` from the proposal; review sources also require `user_ref`, and promotion requires matching `consent`. Record only real user authorization; do not invent approval. If the digest changes, show the new proposal and obtain authorization for it. Report success only after the receipt and verification. Session grants and confirmation are caller-provided and cannot prevent forgery by another process with the same OS permissions; the independent knowledge API remains available.
